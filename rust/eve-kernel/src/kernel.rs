use std::env;
use std::fs;
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

#[derive(Clone, Debug)]
pub struct KernelConfig {
    pub host: String,
    pub port: u16,
    pub project_root: PathBuf,
}

#[derive(Clone, Debug)]
pub struct EveKernel {
    config: KernelConfig,
}

impl EveKernel {
    pub fn new(config: KernelConfig) -> Self {
        Self { config }
    }

    pub fn host(&self) -> &str {
        &self.config.host
    }

    pub fn port(&self) -> u16 {
        self.config.port
    }

    pub fn project_root(&self) -> &Path {
        &self.config.project_root
    }

    pub fn healthz_json(&self) -> String {
        format!(
            "{{\"ok\":true,\"service\":\"eve-kernel\",\"version\":\"0.1.0\",\"timestamp\":\"{}\"}}",
            unix_timestamp()
        )
    }

    pub fn status_json(&self) -> String {
        let state = self.read_json_object(".eve/state.json");
        let model_watchdog = self.read_json_object(".eve/model_watchdog_status.json");
        let system_snapshot = self.read_json_object(".eve/system_snapshot.json");

        format!(
            concat!(
                "{{",
                "\"ok\":true,",
                "\"data\":{{",
                "\"service\":\"eve-kernel\",",
                "\"version\":\"0.1.0\",",
                "\"timestamp\":\"{}\",",
                "\"project_root\":{},",
                "\"state\":{},",
                "\"model_watchdog\":{},",
                "\"system_snapshot\":{}",
                "}}",
                "}}"
            ),
            unix_timestamp(),
            json_string(&self.project_root().display().to_string()),
            state,
            model_watchdog,
            system_snapshot
        )
    }

    fn read_json_object(&self, relative_path: &str) -> String {
        let path = self.project_root().join(relative_path);
        match fs::read_to_string(path) {
            Ok(content) => {
                let trimmed = content.trim();
                if trimmed.starts_with('{') || trimmed.starts_with('[') {
                    trimmed.to_string()
                } else {
                    "{}".to_string()
                }
            }
            Err(_) => "{}".to_string(),
        }
    }
}

pub fn default_config() -> KernelConfig {
    let cwd = env::current_dir().unwrap_or_else(|_| PathBuf::from("."));
    KernelConfig {
        host: "127.0.0.1".to_string(),
        port: 8788,
        project_root: cwd,
    }
}

pub fn unix_timestamp() -> String {
    match SystemTime::now().duration_since(UNIX_EPOCH) {
        Ok(duration) => duration.as_secs().to_string(),
        Err(_) => "0".to_string(),
    }
}

pub fn json_string(value: &str) -> String {
    let mut escaped = String::with_capacity(value.len() + 2);
    escaped.push('"');
    for ch in value.chars() {
        match ch {
            '\\' => escaped.push_str("\\\\"),
            '"' => escaped.push_str("\\\""),
            '\n' => escaped.push_str("\\n"),
            '\r' => escaped.push_str("\\r"),
            '\t' => escaped.push_str("\\t"),
            _ => escaped.push(ch),
        }
    }
    escaped.push('"');
    escaped
}
