from fastapi import FastAPI
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from app.Chatbot.wrapper_agent import ask_agent  

app = FastAPI()

# ✅ Allow frontend (React) to call backend

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class Query(BaseModel):
    query: str

@app.post("/ask")
async def ask(query: Query):
    response = await ask_agent(query.query)
    return {"response": response}


#if __name__ == "__main__":
#    uvicorn.run(app, host="0.0.0.0", port=8000)
