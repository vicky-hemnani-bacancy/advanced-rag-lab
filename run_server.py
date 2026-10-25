"""Start the demo app:  .venv\\Scripts\\python run_server.py   ->  http://localhost:8100"""
import uvicorn

if __name__ == "__main__":
    uvicorn.run("api:app", host="127.0.0.1", port=8100, log_level="info")
