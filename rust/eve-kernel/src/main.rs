mod http;
mod kernel;

use std::env;
use std::path::PathBuf;

use kernel::{default_config, EveKernel, KernelConfig};

fn main() {
    let config = parse_args();
    let kernel = EveKernel::new(config);
    if let Err(err) = http::serve(kernel) {
        eprintln!("eve-kernel failed: {}", err);
        std::process::exit(1);
    }
}

fn parse_args() -> KernelConfig {
    let mut config = default_config();
    let mut args = env::args().skip(1);

    while let Some(arg) = args.next() {
        match arg.as_str() {
            "--host" => {
                if let Some(value) = args.next() {
                    config.host = value;
                }
            }
            "--port" => {
                if let Some(value) = args.next() {
                    if let Ok(parsed) = value.parse::<u16>() {
                        config.port = parsed;
                    }
                }
            }
            "--project-root" => {
                if let Some(value) = args.next() {
                    config.project_root = PathBuf::from(value);
                }
            }
            _ => {}
        }
    }

    config
}
