use std::io::{Read, Write};
use std::net::{TcpListener, TcpStream};
use std::sync::Arc;

use crate::kernel::EveKernel;

pub fn serve(kernel: EveKernel) -> std::io::Result<()> {
    let address = format!("{}:{}", kernel.host(), kernel.port());
    let listener = TcpListener::bind(&address)?;
    println!("eve-kernel listening on http://{}", address);

    let shared = Arc::new(kernel);
    for stream in listener.incoming() {
        match stream {
            Ok(stream) => {
                let kernel = Arc::clone(&shared);
                handle_client(stream, kernel)?;
            }
            Err(err) => eprintln!("accept error: {}", err),
        }
    }
    Ok(())
}

fn handle_client(mut stream: TcpStream, kernel: Arc<EveKernel>) -> std::io::Result<()> {
    let mut buffer = [0_u8; 4096];
    let bytes_read = stream.read(&mut buffer)?;
    if bytes_read == 0 {
        return Ok(());
    }

    let request = String::from_utf8_lossy(&buffer[..bytes_read]);
    let first_line = request.lines().next().unwrap_or("");
    let path = request_path(first_line);

    let (status_line, body) = match path {
        "/healthz" => ("HTTP/1.1 200 OK", kernel.healthz_json()),
        "/v1/status" => ("HTTP/1.1 200 OK", kernel.status_json()),
        _ => (
            "HTTP/1.1 404 Not Found",
            "{\"ok\":false,\"error\":\"not found\"}".to_string(),
        ),
    };

    write_response(&mut stream, status_line, "application/json; charset=utf-8", &body)
}

fn request_path(first_line: &str) -> &str {
    first_line.split_whitespace().nth(1).unwrap_or("/")
}

fn write_response(
    stream: &mut TcpStream,
    status_line: &str,
    content_type: &str,
    body: &str,
) -> std::io::Result<()> {
    let response = format!(
        concat!(
            "{}\r\n",
            "Content-Type: {}\r\n",
            "Content-Length: {}\r\n",
            "Connection: close\r\n",
            "\r\n",
            "{}"
        ),
        status_line,
        content_type,
        body.as_bytes().len(),
        body
    );
    stream.write_all(response.as_bytes())?;
    stream.flush()
}
