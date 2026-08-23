package main

import (
	"context"
	"crypto/sha256"
	"crypto/subtle"
	"database/sql"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"math"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"syscall"
	"time"

	_ "modernc.org/sqlite"
)

const schemaVersion = 1

var sensorySessionMaxEvents = 5000

var sensoryIdentifierPattern = regexp.MustCompile(`[^a-z0-9_.:]`)

var sensoryFeatureLimits = map[string]float64{
	"action_latency_ms":    60000,
	"contact_count":        100,
	"energy_percent":       100,
	"face_count":           32,
	"focus_changes":        100,
	"force_percent":        100,
	"interaction_rate":     100,
	"key_events":           500,
	"luminance_percent":    100,
	"motion_percent":       100,
	"object_count":         128,
	"person_count":         32,
	"pointer_events":       500,
	"position_delta":       100,
	"scene_change_percent": 100,
	"sound_change_percent": 100,
	"source_count":         32,
	"spectral_centroid_hz": 24000,
	"speech_likelihood":    100,
	"zero_crossing_rate":   1,
}

var sensoryFeatureEnums = map[string]map[string]bool{
	"activity_state":   {"quiet": true, "sound": true, "speech_like": true, "active": true, "idle": true, "unknown": true},
	"actuator_state":   {"idle": true, "moving": true, "blocked": true, "complete": true, "unknown": true},
	"focus_state":      {"focused": true, "unfocused": true, "unknown": true},
	"scene_state":      {"stable": true, "movement": true, "large_change": true, "unknown": true},
	"visibility_state": {"visible": true, "hidden": true, "unknown": true},
}

var sensoryBooleanFeatures = map[string]bool{"active": true, "visible": true}

var sensorySources = map[string]bool{
	"eve_app_camera_features":      true,
	"eve_app_interaction_features": true,
	"eve_app_microphone_features":  true,
	"go_private_device_adapter":    true,
	"private_device_adapter":       true,
}

var sensorySubjects = map[string]bool{
	"eve_app_interaction":        true,
	"local_auditory_scene":       true,
	"local_proprioceptive_scene": true,
	"local_scene":                true,
	"local_visual_scene":         true,
}

type SensoryInput struct {
	Modality        string
	SessionID       string
	SessionToken    string
	Source          string
	Subject         string
	Features        map[string]any
	Permission      bool
	Intensity       float64
	Novelty         float64
	Change          float64
	Urgency         float64
	GoalRelevance   float64
	SelfRelevance   float64
	SocialRelevance float64
	Precision       float64
}

type Event struct {
	ID            string         `json:"id"`
	CreatedAt     string         `json:"created_at"`
	Source        string         `json:"source"`
	Actor         string         `json:"actor"`
	Kind          string         `json:"kind"`
	Stream        string         `json:"stream"`
	Subject       string         `json:"subject"`
	CorrelationID string         `json:"correlation_id"`
	CausationID   string         `json:"causation_id"`
	SchemaVersion int            `json:"schema_version"`
	Payload       map[string]any `json:"payload"`
	Metadata      map[string]any `json:"metadata"`
}

type Options struct {
	DBPath string
	Source string
	Actor  string
	JSON   bool
}

func utcNow() string {
	return time.Now().UTC().Format(time.RFC3339)
}

func newID() string {
	return fmt.Sprintf("%d-%d", time.Now().UTC().UnixNano(), os.Getpid())
}

func cleanText(value string, fallback string) string {
	text := strings.TrimSpace(value)
	if text == "" {
		return fallback
	}
	return text
}

func sensoryIdentifier(value string, fallback string) string {
	clean := strings.ToLower(strings.TrimSpace(value))
	clean = strings.ReplaceAll(clean, "-", "_")
	clean = sensoryIdentifierPattern.ReplaceAllString(clean, "_")
	for strings.Contains(clean, "__") {
		clean = strings.ReplaceAll(clean, "__", "_")
	}
	clean = strings.Trim(clean, "_.:")
	if len(clean) > 80 {
		clean = clean[:80]
	}
	if clean == "" {
		return fallback
	}
	return clean
}

func clampSensory(value float64) float64 {
	if math.IsNaN(value) || math.IsInf(value, 0) {
		return 0
	}
	if value < 0 {
		return 0
	}
	if value > 100 {
		return 100
	}
	return value
}

func normalizeSensoryFeatures(features map[string]any) (map[string]any, error) {
	normalized := map[string]any{}
	for rawKey, value := range features {
		key := strings.ToLower(strings.ReplaceAll(strings.TrimSpace(rawKey), "-", "_"))
		if limit, ok := sensoryFeatureLimits[key]; ok {
			number, ok := value.(float64)
			if !ok || math.IsNaN(number) || math.IsInf(number, 0) {
				return nil, fmt.Errorf("sensory feature %s must be numeric", key)
			}
			if number < 0 {
				number = 0
			}
			if number > limit {
				number = limit
			}
			normalized[key] = number
			continue
		}
		if allowed, ok := sensoryFeatureEnums[key]; ok {
			text, ok := value.(string)
			if !ok {
				return nil, fmt.Errorf("sensory feature %s must be categorical text", key)
			}
			text = sensoryIdentifier(text, "unknown")
			if !allowed[text] {
				text = "unknown"
			}
			normalized[key] = text
			continue
		}
		if sensoryBooleanFeatures[key] {
			boolean, ok := value.(bool)
			if !ok {
				return nil, fmt.Errorf("sensory feature %s must be boolean", key)
			}
			normalized[key] = boolean
			continue
		}
		return nil, fmt.Errorf("sensory feature is not admitted: %s", key)
	}
	return normalized, nil
}

func sensorySummary(modality string, features map[string]any) string {
	switch modality {
	case "auditory":
		switch fmt.Sprint(features["activity_state"]) {
		case "quiet":
			return "The local acoustic scene is quiet; no recording or words were retained."
		case "speech_like":
			return "Speech-band acoustic activity changed nearby; no recording or words were retained."
		default:
			return "The local acoustic scene changed; no recording or words were retained."
		}
	case "visual":
		switch fmt.Sprint(features["scene_state"]) {
		case "stable":
			return "The local visual scene is stable; no frame was retained."
		case "movement":
			return "Movement changed the local visual scene; no frame was retained."
		case "large_change":
			return "The local visual scene changed substantially; no frame was retained."
		default:
			return "Local visual features changed; no frame was retained."
		}
	default:
		return "Aggregate local interaction state changed; no keys or content were retained."
	}
}

func sensoryFingerprint(modality string, source string, subject string, features map[string]any) string {
	signature := map[string]any{}
	for key, value := range features {
		if limit, ok := sensoryFeatureLimits[key]; ok {
			if number, ok := value.(float64); ok {
				width := math.Max(limit/10.0, 0.001)
				signature[key] = int(math.Round(number / width))
			}
			continue
		}
		if _, ok := value.(string); ok {
			signature[key] = value
		} else if _, ok := value.(bool); ok {
			signature[key] = value
		}
	}
	encoded, _ := json.Marshal([]any{modality, source, subject, signature})
	digest := sha256.Sum256(encoded)
	return fmt.Sprintf("%x", digest[:12])
}

func newEvent(kind string, opts Options, stream string, subject string, correlationID string, causationID string, payload map[string]any, metadata map[string]any) Event {
	id := newID()
	if payload == nil {
		payload = map[string]any{}
	}
	if metadata == nil {
		metadata = map[string]any{}
	}
	return Event{
		ID:            id,
		CreatedAt:     utcNow(),
		Source:        cleanText(opts.Source, "go:eve-nervous"),
		Actor:         cleanText(opts.Actor, "eve-nervous"),
		Kind:          cleanText(kind, "event"),
		Stream:        cleanText(stream, "system"),
		Subject:       strings.TrimSpace(subject),
		CorrelationID: cleanText(correlationID, id),
		CausationID:   strings.TrimSpace(causationID),
		SchemaVersion: schemaVersion,
		Payload:       payload,
		Metadata:      metadata,
	}
}

func openDatabase(dbPath string) (*sql.DB, error) {
	if err := os.MkdirAll(filepath.Dir(dbPath), 0o755); err != nil {
		return nil, err
	}
	db, err := sql.Open("sqlite", dbPath)
	if err != nil {
		return nil, err
	}
	db.SetMaxOpenConns(1)
	pragmas := []string{
		"PRAGMA busy_timeout = 10000",
		"PRAGMA foreign_keys = ON",
	}
	for _, pragma := range pragmas {
		if _, err := db.Exec(pragma); err != nil {
			_ = db.Close()
			return nil, err
		}
	}
	return db, nil
}

func withWriterLock(dbPath string, fn func() error) error {
	lockPath := dbPath + ".lock"
	if err := os.MkdirAll(filepath.Dir(lockPath), 0o755); err != nil {
		return err
	}
	lockFile, err := os.OpenFile(lockPath, os.O_CREATE|os.O_RDWR, 0o644)
	if err != nil {
		return err
	}
	defer lockFile.Close()
	if err := syscall.Flock(int(lockFile.Fd()), syscall.LOCK_EX); err != nil {
		return err
	}
	defer syscall.Flock(int(lockFile.Fd()), syscall.LOCK_UN)
	return fn()
}

func ensureSchema(ctx context.Context, dbPath string) error {
	return withWriterLock(dbPath, func() error {
		db, err := openDatabase(dbPath)
		if err != nil {
			return err
		}
		defer db.Close()
		if _, err := db.ExecContext(ctx, "PRAGMA journal_mode = WAL"); err != nil {
			return err
		}
		if _, err := db.ExecContext(ctx, "PRAGMA synchronous = NORMAL"); err != nil {
			return err
		}
		_, err = db.ExecContext(ctx, `
CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    source TEXT NOT NULL,
    actor TEXT NOT NULL,
    kind TEXT NOT NULL,
    stream TEXT NOT NULL,
    subject TEXT NOT NULL,
    correlation_id TEXT NOT NULL,
    causation_id TEXT NOT NULL,
    schema_version INTEGER NOT NULL DEFAULT 1,
    payload_json TEXT NOT NULL,
    metadata_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_stream_created
    ON events(stream, created_at);
CREATE INDEX IF NOT EXISTS idx_events_kind_created
    ON events(kind, created_at);
CREATE INDEX IF NOT EXISTS idx_events_correlation
    ON events(correlation_id);
`)
		return err
	})
}

func insertEvent(ctx context.Context, dbPath string, event Event) error {
	payload, err := json.Marshal(event.Payload)
	if err != nil {
		return err
	}
	metadata, err := json.Marshal(event.Metadata)
	if err != nil {
		return err
	}
	return withWriterLock(dbPath, func() error {
		db, err := openDatabase(dbPath)
		if err != nil {
			return err
		}
		defer db.Close()
		_, err = db.ExecContext(
			ctx,
			`INSERT OR REPLACE INTO events
             (id, created_at, source, actor, kind, stream, subject, correlation_id,
              causation_id, schema_version, payload_json, metadata_json)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
			event.ID,
			event.CreatedAt,
			event.Source,
			event.Actor,
			event.Kind,
			event.Stream,
			event.Subject,
			event.CorrelationID,
			event.CausationID,
			event.SchemaVersion,
			string(payload),
			string(metadata),
		)
		return err
	})
}

func insertSensoryEvent(ctx context.Context, dbPath string, sessionID string, expiresAt time.Time, event Event) error {
	payload, err := json.Marshal(event.Payload)
	if err != nil {
		return err
	}
	metadata, err := json.Marshal(event.Metadata)
	if err != nil {
		return err
	}
	prefix := sessionID + ":"
	return withWriterLock(dbPath, func() error {
		db, err := openDatabase(dbPath)
		if err != nil {
			return err
		}
		defer db.Close()
		var stopCount int
		if err := db.QueryRowContext(
			ctx,
			"SELECT COUNT(*) FROM events WHERE correlation_id = ? AND kind = 'sensory.session.stopped'",
			sessionID,
		).Scan(&stopCount); err != nil {
			return err
		}
		if stopCount > 0 || !expiresAt.After(time.Now().UTC()) {
			return errors.New("sensory session is not active")
		}
		var existing int
		if err := db.QueryRowContext(
			ctx,
			`SELECT COUNT(*) FROM events
			  WHERE stream = 'sensory'
			    AND kind = 'sensory.observed'
			    AND (correlation_id = ? OR substr(correlation_id, 1, ?) = ?)`,
			sessionID,
			len(prefix),
			prefix,
		).Scan(&existing); err != nil {
			return err
		}
		if existing >= sensorySessionMaxEvents {
			return errors.New("sensory session event budget exceeded")
		}
		_, err = db.ExecContext(
			ctx,
			`INSERT OR REPLACE INTO events
			 (id, created_at, source, actor, kind, stream, subject, correlation_id,
			  causation_id, schema_version, payload_json, metadata_json)
			 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
			event.ID,
			event.CreatedAt,
			event.Source,
			event.Actor,
			event.Kind,
			event.Stream,
			event.Subject,
			event.CorrelationID,
			event.CausationID,
			event.SchemaVersion,
			string(payload),
			string(metadata),
		)
		return err
	})
}

func decodeEvent(row scanner) (Event, error) {
	var event Event
	var payloadJSON string
	var metadataJSON string
	if err := row.Scan(
		&event.ID,
		&event.CreatedAt,
		&event.Source,
		&event.Actor,
		&event.Kind,
		&event.Stream,
		&event.Subject,
		&event.CorrelationID,
		&event.CausationID,
		&event.SchemaVersion,
		&payloadJSON,
		&metadataJSON,
	); err != nil {
		return Event{}, err
	}
	event.Payload = map[string]any{}
	event.Metadata = map[string]any{}
	_ = json.Unmarshal([]byte(payloadJSON), &event.Payload)
	_ = json.Unmarshal([]byte(metadataJSON), &event.Metadata)
	return event, nil
}

type scanner interface {
	Scan(dest ...any) error
}

func nextPendingJob(ctx context.Context, dbPath string) (Event, bool, error) {
	db, err := openDatabase(dbPath)
	if err != nil {
		return Event{}, false, err
	}
	defer db.Close()
	row := db.QueryRowContext(
		ctx,
		`SELECT id, created_at, source, actor, kind, stream, subject, correlation_id,
                causation_id, schema_version, payload_json, metadata_json
           FROM events AS e
          WHERE e.kind = 'tool.job.requested'
            AND NOT EXISTS (
                SELECT 1
                  FROM events AS claimed
                 WHERE claimed.causation_id = e.id
                   AND claimed.kind IN ('tool.job.claimed', 'tool.job.completed', 'tool.job.failed')
            )
          ORDER BY e.created_at ASC, e.id ASC
          LIMIT 1`,
	)
	event, err := decodeEvent(row)
	if errors.Is(err, sql.ErrNoRows) {
		return Event{}, false, nil
	}
	if err != nil {
		return Event{}, false, err
	}
	return event, true, nil
}

func recordHeartbeat(ctx context.Context, opts Options) (Event, error) {
	event := newEvent(
		"nervous.heartbeat",
		opts,
		"system",
		"eve-nervous",
		"",
		"",
		map[string]any{"status": "alive"},
		map[string]any{"component": "go/eve-nervous"},
	)
	return event, insertEvent(ctx, opts.DBPath, event)
}

func enqueueJob(ctx context.Context, opts Options, tool string, message string) (Event, error) {
	payload := map[string]any{
		"tool": cleanText(tool, "echo"),
		"args": map[string]any{
			"message": message,
		},
	}
	event := newEvent(
		"tool.job.requested",
		opts,
		"tool",
		cleanText(tool, "echo"),
		"",
		"",
		payload,
		map[string]any{"component": "go/eve-nervous"},
	)
	return event, insertEvent(ctx, opts.DBPath, event)
}

func executeTool(job Event) (string, map[string]any) {
	tool, _ := job.Payload["tool"].(string)
	args, _ := job.Payload["args"].(map[string]any)
	switch tool {
	case "echo":
		return "completed", map[string]any{
			"tool":    "echo",
			"message": fmt.Sprint(args["message"]),
		}
	case "event.contract.check":
		return "completed", map[string]any{
			"tool": "event.contract.check",
			"required_fields": []string{
				"id", "created_at", "source", "actor", "kind", "stream",
				"subject", "correlation_id", "causation_id", "schema_version",
				"payload", "metadata",
			},
			"ok": true,
		}
	default:
		return "failed", map[string]any{
			"tool":  cleanText(tool, "unknown"),
			"error": "unsupported_tool",
		}
	}
}

func processOnePendingJob(ctx context.Context, opts Options) ([]Event, bool, error) {
	job, ok, err := nextPendingJob(ctx, opts.DBPath)
	if err != nil {
		return nil, false, err
	}
	if !ok {
		return nil, false, nil
	}
	claim := newEvent(
		"tool.job.claimed",
		opts,
		"tool",
		job.Subject,
		job.CorrelationID,
		job.ID,
		map[string]any{
			"job_id": job.ID,
			"tool":   job.Payload["tool"],
		},
		map[string]any{"component": "go/eve-nervous"},
	)
	if err := insertEvent(ctx, opts.DBPath, claim); err != nil {
		return nil, false, err
	}
	events := []Event{claim}
	status, result := executeTool(job)
	completedKind := "tool.job.completed"
	if status != "completed" {
		completedKind = "tool.job.failed"
	}
	completed := newEvent(
		completedKind,
		opts,
		"tool",
		job.Subject,
		job.CorrelationID,
		job.ID,
		map[string]any{
			"job_id":   job.ID,
			"claim_id": claim.ID,
			"status":   status,
			"result":   result,
		},
		map[string]any{"component": "go/eve-nervous"},
	)
	if err := insertEvent(ctx, opts.DBPath, completed); err != nil {
		return events, false, err
	}
	events = append(events, completed)
	actionResult := newEvent(
		"action.result.recorded",
		opts,
		"action",
		job.Subject,
		job.CorrelationID,
		completed.ID,
		map[string]any{
			"job_id":         job.ID,
			"tool_event_id":  completed.ID,
			"status":         status,
			"result":         result,
			"source_surface": "go/eve-nervous",
		},
		map[string]any{"component": "go/eve-nervous"},
	)
	if err := insertEvent(ctx, opts.DBPath, actionResult); err != nil {
		return events, false, err
	}
	events = append(events, actionResult)
	return events, true, nil
}

func runOnce(ctx context.Context, opts Options) ([]Event, error) {
	heartbeat, err := recordHeartbeat(ctx, opts)
	if err != nil {
		return nil, err
	}
	events := []Event{heartbeat}
	jobEvents, _, err := processOnePendingJob(ctx, opts)
	if err != nil {
		return events, err
	}
	events = append(events, jobEvents...)
	return events, nil
}

type RunLoopConfig struct {
	Duration          time.Duration
	Interval          time.Duration
	IdleBackoff       time.Duration
	HeartbeatInterval time.Duration
	MaxJobs           int
}

func normalizeRunLoopConfig(cfg RunLoopConfig) RunLoopConfig {
	if cfg.Duration <= 0 {
		cfg.Duration = 30 * time.Second
	}
	if cfg.Interval <= 0 {
		cfg.Interval = 1 * time.Second
	}
	if cfg.IdleBackoff <= 0 {
		cfg.IdleBackoff = 2 * time.Second
	}
	if cfg.HeartbeatInterval <= 0 {
		cfg.HeartbeatInterval = 15 * time.Second
	}
	if cfg.MaxJobs < 0 {
		cfg.MaxJobs = 0
	}
	return cfg
}

func runLoop(ctx context.Context, opts Options, cfg RunLoopConfig) ([]Event, error) {
	cfg = normalizeRunLoopConfig(cfg)
	started := time.Now()
	deadline := started.Add(cfg.Duration)
	nextHeartbeat := time.Time{}
	processedJobs := 0
	events := []Event{}
	for time.Now().Before(deadline) {
		if cfg.MaxJobs > 0 && processedJobs >= cfg.MaxJobs {
			break
		}
		select {
		case <-ctx.Done():
			return events, ctx.Err()
		default:
		}
		now := time.Now()
		if nextHeartbeat.IsZero() || !now.Before(nextHeartbeat) {
			heartbeat, err := recordHeartbeat(ctx, opts)
			if err != nil {
				return events, err
			}
			events = append(events, heartbeat)
			nextHeartbeat = now.Add(cfg.HeartbeatInterval)
		}
		jobEvents, processed, err := processOnePendingJob(ctx, opts)
		if err != nil {
			return events, err
		}
		if processed {
			processedJobs++
			events = append(events, jobEvents...)
			sleepUntil(ctx, cfg.Interval, deadline)
			continue
		}
		sleepUntil(ctx, cfg.IdleBackoff, deadline)
	}
	summary := newEvent(
		"nervous.run.completed",
		opts,
		"system",
		"eve-nervous",
		"",
		"",
		map[string]any{
			"processed_jobs":         processedJobs,
			"emitted_events":         len(events),
			"duration_seconds":       int(time.Since(started).Seconds()),
			"configured_seconds":     int(cfg.Duration.Seconds()),
			"max_jobs":               cfg.MaxJobs,
			"idle_backoff_seconds":   cfg.IdleBackoff.Seconds(),
			"heartbeat_interval_sec": cfg.HeartbeatInterval.Seconds(),
		},
		map[string]any{"component": "go/eve-nervous"},
	)
	if err := insertEvent(ctx, opts.DBPath, summary); err != nil {
		return events, err
	}
	events = append(events, summary)
	return events, nil
}

func sleepUntil(ctx context.Context, duration time.Duration, deadline time.Time) {
	if duration <= 0 {
		return
	}
	remaining := time.Until(deadline)
	if remaining <= 0 {
		return
	}
	if duration > remaining {
		duration = remaining
	}
	timer := time.NewTimer(duration)
	defer timer.Stop()
	select {
	case <-ctx.Done():
	case <-timer.C:
	}
}

func recordManualResult(ctx context.Context, opts Options, subject string, status string, message string) (Event, error) {
	event := newEvent(
		"action.result.recorded",
		opts,
		"action",
		cleanText(subject, "manual"),
		"",
		"",
		map[string]any{
			"status":  cleanText(status, "completed"),
			"message": message,
		},
		map[string]any{"component": "go/eve-nervous"},
	)
	return event, insertEvent(ctx, opts.DBPath, event)
}

func validateSensorySession(ctx context.Context, opts Options, input SensoryInput) (map[string]any, error) {
	if !strings.HasPrefix(input.SessionID, "sensory-") || input.SessionToken == "" {
		return nil, errors.New("an active sensory session id and token are required")
	}
	db, err := openDatabase(opts.DBPath)
	if err != nil {
		return nil, err
	}
	defer db.Close()
	row := db.QueryRowContext(
		ctx,
		`SELECT id, created_at, source, actor, kind, stream, subject, correlation_id,
		        causation_id, schema_version, payload_json, metadata_json
		   FROM events
		  WHERE correlation_id = ? AND kind = 'sensory.session.started'
		  ORDER BY created_at DESC, id DESC
		  LIMIT 1`,
		input.SessionID,
	)
	started, err := decodeEvent(row)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, errors.New("sensory session was not found")
	}
	if err != nil {
		return nil, err
	}
	var stopCount int
	if err := db.QueryRowContext(
		ctx,
		"SELECT COUNT(*) FROM events WHERE correlation_id = ? AND kind = 'sensory.session.stopped'",
		input.SessionID,
	).Scan(&stopCount); err != nil {
		return nil, err
	}
	if stopCount > 0 {
		return nil, errors.New("sensory session is stopped")
	}
	session, _ := started.Payload["session"].(map[string]any)
	expiresText := fmt.Sprint(session["expires_at"])
	expiresAt, err := time.Parse(time.RFC3339, expiresText)
	if err != nil || !expiresAt.After(time.Now().UTC()) {
		return nil, errors.New("sensory session is expired")
	}
	expectedHash := fmt.Sprint(started.Metadata["session_token_hash"])
	actual := sha256.Sum256([]byte(input.SessionToken))
	actualHash := fmt.Sprintf("%x", actual[:])
	if expectedHash == "" || subtle.ConstantTimeCompare([]byte(expectedHash), []byte(actualHash)) != 1 {
		return nil, errors.New("sensory session token is invalid")
	}
	modalityAllowed := false
	switch modalities := session["modalities"].(type) {
	case []any:
		for _, item := range modalities {
			if fmt.Sprint(item) == input.Modality {
				modalityAllowed = true
				break
			}
		}
	case []string:
		for _, item := range modalities {
			if item == input.Modality {
				modalityAllowed = true
				break
			}
		}
	}
	if !modalityAllowed {
		return nil, fmt.Errorf("sensory modality is not admitted for this session: %s", input.Modality)
	}
	return session, nil
}

func recordSensoryObservation(ctx context.Context, opts Options, input SensoryInput) (Event, error) {
	input.Modality = strings.ToLower(strings.TrimSpace(input.Modality))
	if input.Modality != "auditory" && input.Modality != "visual" && input.Modality != "proprioceptive" {
		return Event{}, fmt.Errorf("unsupported sensory modality: %s", input.Modality)
	}
	if (input.Modality == "auditory" || input.Modality == "visual") && !input.Permission {
		return Event{}, fmt.Errorf("%s input requires current device permission", input.Modality)
	}
	for name, value := range map[string]float64{
		"intensity": input.Intensity, "novelty": input.Novelty, "change": input.Change,
		"urgency": input.Urgency, "goal_relevance": input.GoalRelevance,
		"self_relevance": input.SelfRelevance, "social_relevance": input.SocialRelevance,
		"precision": input.Precision,
	} {
		if math.IsNaN(value) || math.IsInf(value, 0) {
			return Event{}, fmt.Errorf("sensory field %s must be finite", name)
		}
	}
	session, err := validateSensorySession(ctx, opts, input)
	if err != nil {
		return Event{}, err
	}
	expiresAt, err := time.Parse(time.RFC3339, fmt.Sprint(session["expires_at"]))
	if err != nil {
		return Event{}, errors.New("sensory session expiry evidence is invalid")
	}
	features, err := normalizeSensoryFeatures(input.Features)
	if err != nil {
		return Event{}, err
	}
	if len(features) == 0 {
		return Event{}, errors.New("at least one admitted sensory feature is required")
	}
	observedAt := utcNow()
	source := sensoryIdentifier(input.Source, "go_private_device_adapter")
	if !sensorySources[source] {
		source = "go_private_device_adapter"
	}
	defaultSubject := "local_" + input.Modality + "_scene"
	subject := sensoryIdentifier(input.Subject, defaultSubject)
	if !sensorySubjects[subject] {
		subject = defaultSubject
	}
	adapterEvent := map[string]any{
		"schema_version":        "eve.sensory_adapter_event.v1",
		"id":                    "adapter_" + newID(),
		"observed_at":           observedAt,
		"modality":              input.Modality,
		"source":                source,
		"subject":               subject,
		"correlation_id":        input.SessionID,
		"summary":               sensorySummary(input.Modality, features),
		"features":              features,
		"fingerprint":           sensoryFingerprint(input.Modality, source, subject, features),
		"intensity":             clampSensory(input.Intensity),
		"novelty":               clampSensory(input.Novelty),
		"change":                clampSensory(input.Change),
		"urgency":               clampSensory(input.Urgency),
		"goal_relevance":        clampSensory(input.GoalRelevance),
		"self_relevance":        clampSensory(input.SelfRelevance),
		"social_relevance":      clampSensory(input.SocialRelevance),
		"precision":             clampSensory(input.Precision),
		"direct_human":          false,
		"safety_critical":       false,
		"privacy":               "local_private",
		"persistence":           "features_only",
		"private_adapter_event": true,
		"permission_granted":    true,
		"requires_permission":   false,
	}
	event := newEvent(
		"sensory.observed",
		opts,
		"sensory",
		subject,
		input.SessionID,
		"",
		map[string]any{"event": adapterEvent},
		map[string]any{
			"component":                    "go/eve-nervous",
			"session_id":                   input.SessionID,
			"persistence":                  "features_only",
			"raw_device_capture_persisted": false,
			"authority":                    "observation_only",
		},
	)
	return event, insertSensoryEvent(ctx, opts.DBPath, input.SessionID, expiresAt, event)
}

func readSensorySessionToken(environmentName string, tokenFile string) (string, error) {
	if strings.TrimSpace(tokenFile) != "" {
		cleanPath := filepath.Clean(tokenFile)
		info, err := os.Stat(cleanPath)
		if err != nil {
			return "", err
		}
		if !info.Mode().IsRegular() {
			return "", errors.New("sensory session token path must be a regular file")
		}
		if info.Mode().Perm()&0o077 != 0 {
			return "", errors.New("sensory session token file must not be accessible by group or other users")
		}
		data, err := os.ReadFile(cleanPath)
		if err != nil {
			return "", err
		}
		if token := strings.TrimSpace(string(data)); token != "" {
			return token, nil
		}
		return "", errors.New("sensory session token file is empty")
	}
	name := cleanText(environmentName, "EVE_SENSORY_SESSION_TOKEN")
	if token := strings.TrimSpace(os.Getenv(name)); token != "" {
		return token, nil
	}
	return "", fmt.Errorf("sensory session token is missing from %s", name)
}

func printEvents(events []Event, asJSON bool) error {
	if asJSON {
		encoded, err := json.MarshalIndent(events, "", "  ")
		if err != nil {
			return err
		}
		fmt.Println(string(encoded))
		return nil
	}
	for _, event := range events {
		fmt.Printf("%s | %s | %s | subject=%s | id=%s\n", event.CreatedAt, event.Stream, event.Kind, event.Subject, event.ID)
	}
	return nil
}

func runCLI(args []string) int {
	global := flag.NewFlagSet("eve-nervous", flag.ContinueOnError)
	global.SetOutput(os.Stderr)
	opts := Options{}
	global.StringVar(&opts.DBPath, "db", ".eve/operational_state.sqlite3", "Path to Eve's operational SQLite database.")
	global.StringVar(&opts.Source, "source", "go:eve-nervous", "Event source label.")
	global.StringVar(&opts.Actor, "actor", "eve-nervous", "Event actor label.")
	global.BoolVar(&opts.JSON, "json", false, "Print JSON output.")
	if err := global.Parse(args); err != nil {
		return 2
	}
	rest := global.Args()
	if len(rest) == 0 {
		fmt.Fprintln(os.Stderr, "usage: eve-nervous --db <path> <heartbeat|enqueue|once|run|result|sense> [flags]")
		return 2
	}
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Minute)
	defer cancel()
	if err := ensureSchema(ctx, opts.DBPath); err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 1
	}
	switch rest[0] {
	case "heartbeat":
		event, err := recordHeartbeat(ctx, opts)
		if err != nil {
			fmt.Fprintln(os.Stderr, err)
			return 1
		}
		if err := printEvents([]Event{event}, opts.JSON); err != nil {
			fmt.Fprintln(os.Stderr, err)
			return 1
		}
	case "enqueue":
		fs := flag.NewFlagSet("enqueue", flag.ContinueOnError)
		fs.SetOutput(os.Stderr)
		tool := fs.String("tool", "echo", "Tool name to request.")
		message := fs.String("message", "", "Tool message/argument.")
		if err := fs.Parse(rest[1:]); err != nil {
			return 2
		}
		event, err := enqueueJob(ctx, opts, *tool, *message)
		if err != nil {
			fmt.Fprintln(os.Stderr, err)
			return 1
		}
		if err := printEvents([]Event{event}, opts.JSON); err != nil {
			fmt.Fprintln(os.Stderr, err)
			return 1
		}
	case "once":
		events, err := runOnce(ctx, opts)
		if err != nil {
			fmt.Fprintln(os.Stderr, err)
			return 1
		}
		if err := printEvents(events, opts.JSON); err != nil {
			fmt.Fprintln(os.Stderr, err)
			return 1
		}
	case "run":
		fs := flag.NewFlagSet("run", flag.ContinueOnError)
		fs.SetOutput(os.Stderr)
		duration := fs.Duration("duration", 30*time.Second, "How long to run the worker loop.")
		interval := fs.Duration("interval", 1*time.Second, "Delay after a processed job.")
		idleBackoff := fs.Duration("idle-backoff", 2*time.Second, "Delay when no job is available.")
		heartbeatInterval := fs.Duration("heartbeat-interval", 15*time.Second, "Heartbeat cadence while the worker runs.")
		maxJobs := fs.Int("max-jobs", 10, "Maximum jobs to process before exiting. Use 0 for duration-only.")
		if err := fs.Parse(rest[1:]); err != nil {
			return 2
		}
		events, err := runLoop(ctx, opts, RunLoopConfig{
			Duration:          *duration,
			Interval:          *interval,
			IdleBackoff:       *idleBackoff,
			HeartbeatInterval: *heartbeatInterval,
			MaxJobs:           *maxJobs,
		})
		if err != nil {
			fmt.Fprintln(os.Stderr, err)
			return 1
		}
		if err := printEvents(events, opts.JSON); err != nil {
			fmt.Fprintln(os.Stderr, err)
			return 1
		}
	case "result":
		fs := flag.NewFlagSet("result", flag.ContinueOnError)
		fs.SetOutput(os.Stderr)
		subject := fs.String("subject", "manual", "Action-result subject.")
		status := fs.String("status", "completed", "Action-result status.")
		message := fs.String("message", "", "Action-result message.")
		if err := fs.Parse(rest[1:]); err != nil {
			return 2
		}
		event, err := recordManualResult(ctx, opts, *subject, *status, *message)
		if err != nil {
			fmt.Fprintln(os.Stderr, err)
			return 1
		}
		if err := printEvents([]Event{event}, opts.JSON); err != nil {
			fmt.Fprintln(os.Stderr, err)
			return 1
		}
	case "sense":
		fs := flag.NewFlagSet("sense", flag.ContinueOnError)
		fs.SetOutput(os.Stderr)
		modality := fs.String("modality", "", "auditory, visual, or proprioceptive.")
		sessionID := fs.String("session", "", "Active Eve sensory session id.")
		tokenEnvironment := fs.String("session-token-env", "EVE_SENSORY_SESSION_TOKEN", "Environment variable containing the session token.")
		tokenFile := fs.String("session-token-file", "", "Optional local file containing the session token.")
		permission := fs.Bool("permission", false, "Assert current OS/device permission for auditory or visual input.")
		source := fs.String("sensor-source", "go_private_device_adapter", "Low-entropy source identifier.")
		subject := fs.String("subject", "", "Low-entropy tracked subject identifier.")
		featuresJSON := fs.String("features-json", "{}", "JSON object of admitted numeric/categorical features only.")
		intensity := fs.Float64("intensity", 35, "Signal intensity from 0 to 100.")
		novelty := fs.Float64("novelty", 50, "Signal novelty from 0 to 100.")
		change := fs.Float64("change", 0, "Signal change from 0 to 100.")
		urgency := fs.Float64("urgency", 20, "Signal urgency from 0 to 100.")
		goalRelevance := fs.Float64("goal-relevance", 35, "Goal relevance from 0 to 100.")
		selfRelevance := fs.Float64("self-relevance", 35, "Self relevance from 0 to 100.")
		socialRelevance := fs.Float64("social-relevance", 0, "Social relevance from 0 to 100.")
		precision := fs.Float64("precision", 70, "Feature precision from 0 to 100.")
		if err := fs.Parse(rest[1:]); err != nil {
			return 2
		}
		if len(*featuresJSON) > 8192 {
			fmt.Fprintln(os.Stderr, "sensory feature payload is too large")
			return 2
		}
		features := map[string]any{}
		if err := json.Unmarshal([]byte(*featuresJSON), &features); err != nil {
			fmt.Fprintln(os.Stderr, "features-json must be a JSON object:", err)
			return 2
		}
		token, err := readSensorySessionToken(*tokenEnvironment, *tokenFile)
		if err != nil {
			fmt.Fprintln(os.Stderr, err)
			return 1
		}
		event, err := recordSensoryObservation(ctx, opts, SensoryInput{
			Modality:        *modality,
			SessionID:       *sessionID,
			SessionToken:    token,
			Source:          *source,
			Subject:         *subject,
			Features:        features,
			Permission:      *permission,
			Intensity:       *intensity,
			Novelty:         *novelty,
			Change:          *change,
			Urgency:         *urgency,
			GoalRelevance:   *goalRelevance,
			SelfRelevance:   *selfRelevance,
			SocialRelevance: *socialRelevance,
			Precision:       *precision,
		})
		if err != nil {
			fmt.Fprintln(os.Stderr, err)
			return 1
		}
		if err := printEvents([]Event{event}, opts.JSON); err != nil {
			fmt.Fprintln(os.Stderr, err)
			return 1
		}
	default:
		fmt.Fprintf(os.Stderr, "unknown command: %s\n", rest[0])
		return 2
	}
	return 0
}

func main() {
	os.Exit(runCLI(os.Args[1:]))
}
