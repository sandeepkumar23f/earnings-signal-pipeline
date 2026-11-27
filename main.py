import uvicorn
from src.config import PORT

if __name__ == "__main__":
    print(f"Starting Concall Pulse pipeline + WebSocket (/ws) + UI on http://localhost:{PORT}")
    uvicorn.run("src.serve.app:app", host="0.0.0.0", port=PORT, reload=False)