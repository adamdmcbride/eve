package main

import (
	"context"
	"crypto/sha256"
	"database/sql"
	"encoding/json"
	"fmt"
	"math"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func testOptions(t *testing.T) Options {
	t.Helper()
	return Options{
		DBPath: filepath.Join(t.TempDir(), "operational_state.sqlite3"),
		Source: "test:eve-nervous",
		Actor:  "eve-nervous-test",
	}
}

func countEvents(t *testing.T, dbPath string, kind string) int {
	t.Helper()
	db, err := openDatabase(dbPath)
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	row := db.QueryRow("SELECT COUNT(*) FROM events WHERE kind = ?", kind)
	var count int
	if err := row.Scan(&count); err != nil {
		t.Fatal(err)
	}
	return count
}

func payloadForKind(t *testing.T, dbPath string, kind string) map[string]any {
	t.Helper()
	db, err := openDatabase(dbPath)
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	row := db.QueryRow("SELECT payload_json FROM events WHERE kind = ? ORDER BY created_at DESC, id DESC LIMIT 1", kind)
	var raw string
	if err := row.Scan(&raw); err != nil {
		if err == sql.ErrNoRows {
			t.Fatalf("no event for kind %s", kind)
		}
		t.Fatal(err)
	}
	var payload map[string]any
	if err := json.Unmarshal([]byte(raw), &payload); err != nil {
		t.Fatal(err)
	}
	return payload
}

func createSensorySession(t *testing.T, ctx context.Context, opts Options, modalities []string) (string, string) {
	t.Helper()
	sessionID := "sensory-test-session"
	token := "test-high-entropy-session-token"
	tokenHash := sha256.Sum256([]byte(token))
	values := make([]any, 0, len(modalities))
	for _, modality := range modalities {
		values = append(values, modality)
	}
	event := newEvent(
		"sensory.session.started",
		opts,
		"sensory",
		"private_device_session",
		sessionID,
		"",
		map[string]any{
			"session": map[string]any{
				"session_id": sessionID,
				"created_at": utcNow(),
				"expires_at": time.Now().UTC().Add(10 * time.Minute).Format(time.RFC3339),
				"status":     "active",
				"modalities": values,
			},
		},
		map[string]any{"session_token_hash": fmt.Sprintf("%x", tokenHash[:])},
	)
	if err := insertEvent(ctx, opts.DBPath, event); err != nil {
		t.Fatal(err)
	}
	return sessionID, token
}

func TestHeartbeatWritesEvent(t *testing.T) {
	ctx := context.Background()
	opts := testOptions(t)
	if err := ensureSchema(ctx, opts.DBPath); err != nil {
		t.Fatal(err)
	}
	event, err := recordHeartbeat(ctx, opts)
	if err != nil {
		t.Fatal(err)
	}
	if event.Kind != "nervous.heartbeat" {
		t.Fatalf("unexpected kind %s", event.Kind)
	}
	if event.CorrelationID == "" {
		t.Fatal("correlation id should default to event id")
	}
	if count := countEvents(t, opts.DBPath, "nervous.heartbeat"); count != 1 {
		t.Fatalf("heartbeat count = %d", count)
	}
}

func TestRunOnceClaimsEchoJobAndRecordsActionResult(t *testing.T) {
	ctx := context.Background()
	opts := testOptions(t)
	if err := ensureSchema(ctx, opts.DBPath); err != nil {
		t.Fatal(err)
	}
	job, err := enqueueJob(ctx, opts, "echo", "hello from Go")
	if err != nil {
		t.Fatal(err)
	}
	events, err := runOnce(ctx, opts)
	if err != nil {
		t.Fatal(err)
	}
	if len(events) != 4 {
		t.Fatalf("runOnce wrote %d events, want 4", len(events))
	}
	if count := countEvents(t, opts.DBPath, "tool.job.claimed"); count != 1 {
		t.Fatalf("claim count = %d", count)
	}
	if count := countEvents(t, opts.DBPath, "tool.job.completed"); count != 1 {
		t.Fatalf("completed count = %d", count)
	}
	if count := countEvents(t, opts.DBPath, "action.result.recorded"); count != 1 {
		t.Fatalf("action result count = %d", count)
	}
	payload := payloadForKind(t, opts.DBPath, "action.result.recorded")
	if payload["job_id"] != job.ID {
		t.Fatalf("action result job_id = %v, want %s", payload["job_id"], job.ID)
	}
}

func TestRunLoopProcessesBoundedJobsAndWritesSummary(t *testing.T) {
	ctx := context.Background()
	opts := testOptions(t)
	if err := ensureSchema(ctx, opts.DBPath); err != nil {
		t.Fatal(err)
	}
	if _, err := enqueueJob(ctx, opts, "echo", "first"); err != nil {
		t.Fatal(err)
	}
	if _, err := enqueueJob(ctx, opts, "echo", "second"); err != nil {
		t.Fatal(err)
	}
	events, err := runLoop(ctx, opts, RunLoopConfig{
		Duration:          200000000,
		Interval:          1000000,
		IdleBackoff:       1000000,
		HeartbeatInterval: 10000000,
		MaxJobs:           2,
	})
	if err != nil {
		t.Fatal(err)
	}
	if len(events) < 8 {
		t.Fatalf("runLoop wrote %d events, want at least 8", len(events))
	}
	if count := countEvents(t, opts.DBPath, "tool.job.completed"); count != 2 {
		t.Fatalf("completed count = %d", count)
	}
	if count := countEvents(t, opts.DBPath, "action.result.recorded"); count != 2 {
		t.Fatalf("action result count = %d", count)
	}
	if count := countEvents(t, opts.DBPath, "nervous.run.completed"); count != 1 {
		t.Fatalf("summary count = %d", count)
	}
	payload := payloadForKind(t, opts.DBPath, "nervous.run.completed")
	if payload["processed_jobs"] != float64(2) {
		t.Fatalf("processed_jobs = %v, want 2", payload["processed_jobs"])
	}
}

func TestSensoryObservationRequiresSessionAndPersistsFeaturesOnly(t *testing.T) {
	ctx := context.Background()
	opts := testOptions(t)
	if err := ensureSchema(ctx, opts.DBPath); err != nil {
		t.Fatal(err)
	}
	sessionID, token := createSensorySession(t, ctx, opts, []string{"auditory"})
	event, err := recordSensoryObservation(ctx, opts, SensoryInput{
		Modality:     "auditory",
		SessionID:    sessionID,
		SessionToken: token,
		Permission:   true,
		Source:       "USB microphone 1",
		Subject:      "local scene",
		Features: map[string]any{
			"energy_percent":    22.0,
			"activity_state":    "speech_like",
			"speech_likelihood": 68.0,
		},
		Novelty:   72,
		Change:    65,
		Precision: 88,
	})
	if err != nil {
		t.Fatal(err)
	}
	if event.Kind != "sensory.observed" || event.Stream != "sensory" {
		t.Fatalf("unexpected sensory event: %#v", event)
	}
	payload := payloadForKind(t, opts.DBPath, "sensory.observed")
	adapter, ok := payload["event"].(map[string]any)
	if !ok {
		t.Fatalf("missing adapter event: %#v", payload)
	}
	if adapter["persistence"] != "features_only" || adapter["private_adapter_event"] != true {
		t.Fatalf("privacy contract missing: %#v", adapter)
	}
	if adapter["source"] != "go_private_device_adapter" || adapter["subject"] != "local_scene" {
		t.Fatalf("unadmitted identifiers should not survive: %#v", adapter)
	}
	if adapter["fingerprint"] == "" {
		t.Fatalf("feature-derived fingerprint is missing: %#v", adapter)
	}
	if _, exists := adapter["audio"]; exists {
		t.Fatal("raw audio must not be persisted")
	}
	if _, exists := adapter["transcript"]; exists {
		t.Fatal("transcript must not be persisted")
	}
	if count := countEvents(t, opts.DBPath, "sensory.observed"); count != 1 {
		t.Fatalf("sensory observation count = %d", count)
	}
	previousLimit := sensorySessionMaxEvents
	sensorySessionMaxEvents = 1
	defer func() { sensorySessionMaxEvents = previousLimit }()
	if _, err := recordSensoryObservation(ctx, opts, SensoryInput{
		Modality:     "auditory",
		SessionID:    sessionID,
		SessionToken: token,
		Permission:   true,
		Features:     map[string]any{"energy_percent": 10.0},
	}); err == nil || !strings.Contains(err.Error(), "event budget exceeded") {
		t.Fatalf("expected durable sensory event budget error, got %v", err)
	}
}

func TestSensoryObservationRejectsRawUnknownFeaturesAndBadPermission(t *testing.T) {
	ctx := context.Background()
	opts := testOptions(t)
	if err := ensureSchema(ctx, opts.DBPath); err != nil {
		t.Fatal(err)
	}
	sessionID, token := createSensorySession(t, ctx, opts, []string{"auditory", "visual"})
	_, err := recordSensoryObservation(ctx, opts, SensoryInput{
		Modality:     "auditory",
		SessionID:    sessionID,
		SessionToken: token,
		Features:     map[string]any{"energy_percent": 10.0},
	})
	if err == nil {
		t.Fatal("auditory input without current permission should fail")
	}
	_, err = recordSensoryObservation(ctx, opts, SensoryInput{
		Modality:     "visual",
		SessionID:    sessionID,
		SessionToken: token,
		Permission:   true,
		Features:     map[string]any{"pixels": "forbidden"},
	})
	if err == nil {
		t.Fatal("raw or unknown features should fail closed")
	}
	_, err = recordSensoryObservation(ctx, opts, SensoryInput{
		Modality:     "visual",
		SessionID:    sessionID,
		SessionToken: "wrong-token",
		Permission:   true,
		Features:     map[string]any{"motion_percent": 20.0},
	})
	if err == nil {
		t.Fatal("invalid sensory session token should fail")
	}
	_, err = recordSensoryObservation(ctx, opts, SensoryInput{
		Modality:     "visual",
		SessionID:    sessionID,
		SessionToken: token,
		Permission:   true,
		Features:     map[string]any{"motion_percent": math.NaN()},
	})
	if err == nil || !strings.Contains(err.Error(), "must be numeric") {
		t.Fatalf("non-finite feature should fail closed, got %v", err)
	}
	_, err = recordSensoryObservation(ctx, opts, SensoryInput{
		Modality:     "visual",
		SessionID:    sessionID,
		SessionToken: token,
		Permission:   true,
		Features:     map[string]any{"motion_percent": 20.0},
		Novelty:      math.Inf(1),
	})
	if err == nil || !strings.Contains(err.Error(), "must be finite") {
		t.Fatalf("non-finite score should fail closed, got %v", err)
	}
	if count := countEvents(t, opts.DBPath, "sensory.observed"); count != 0 {
		t.Fatalf("rejected observation count = %d", count)
	}
}

func TestSensorySessionTokenFileMustBePrivate(t *testing.T) {
	path := filepath.Join(t.TempDir(), "sensory-token")
	if err := os.WriteFile(path, []byte("private-token\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	if _, err := readSensorySessionToken("", path); err == nil || !strings.Contains(err.Error(), "group or other") {
		t.Fatalf("expected permissive token file to be rejected, got %v", err)
	}
	if err := os.Chmod(path, 0o600); err != nil {
		t.Fatal(err)
	}
	token, err := readSensorySessionToken("", path)
	if err != nil {
		t.Fatal(err)
	}
	if token != "private-token" {
		t.Fatalf("token = %q", token)
	}
}

func TestSensoryInsertRechecksStopInsideWriterLock(t *testing.T) {
	ctx := context.Background()
	opts := testOptions(t)
	if err := ensureSchema(ctx, opts.DBPath); err != nil {
		t.Fatal(err)
	}
	sessionID, _ := createSensorySession(t, ctx, opts, []string{"proprioceptive"})
	stopped := newEvent(
		"sensory.session.stopped",
		opts,
		"sensory",
		"private_device_session",
		sessionID,
		"",
		nil,
		nil,
	)
	if err := insertEvent(ctx, opts.DBPath, stopped); err != nil {
		t.Fatal(err)
	}
	observation := newEvent(
		"sensory.observed",
		opts,
		"sensory",
		"local_proprioceptive_scene",
		sessionID,
		"",
		map[string]any{"event": map[string]any{"persistence": "features_only"}},
		nil,
	)
	err := insertSensoryEvent(
		ctx,
		opts.DBPath,
		sessionID,
		time.Now().UTC().Add(time.Minute),
		observation,
	)
	if err == nil || !strings.Contains(err.Error(), "not active") {
		t.Fatalf("expected stopped session to reject final insert, got %v", err)
	}
	if count := countEvents(t, opts.DBPath, "sensory.observed"); count != 0 {
		t.Fatalf("stopped-session observation count = %d", count)
	}
}
