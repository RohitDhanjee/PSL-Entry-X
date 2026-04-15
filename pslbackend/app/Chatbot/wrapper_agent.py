from langchain_core.messages import HumanMessage, AIMessage
from app.Chatbot.Agent.art_agent import get_agent_executor

async def ask_agent(user_input: str):
    try:
        # create Agent executor 
        agent_executor = get_agent_executor()

        messages = []

        # User input
        messages.append(HumanMessage(content=user_input))

        # Invoke Agent 
        response = await agent_executor.ainvoke({
            "messages": messages,
            "agent_scratchpad": []  # necessary for LangChain agents 
        })

        # Full raw response debug k liye
        # print("FULL RAW RESPONSE:", response)

        # Return output
        return response.get("output", "✅ Got a response, but no output was returned.")
    except Exception as e:
        print("Agent Error:", e)
        return "❌ Sorry, something went wrong. Please try again."
