"""
Convenience script to run the FastAPI server.
"""
import uvicorn

if __name__ == "__main__":
    print("Starting AI Travel Companion API...")
    print("Docs available at: http://localhost:8000/docs")
    print("Chat endpoint: POST http://localhost:8000/api/v1/chat")
    print("\n")
    
    uvicorn.run(
        "api.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )


