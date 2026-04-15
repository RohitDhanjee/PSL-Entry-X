import os
from dotenv import load_dotenv
from langchain_groq import ChatGroq

load_dotenv()
api_key=os.getenv("GROQ_API_KEY")


llm = ChatGroq(model="llama-3.1-8b-instant", api_key=api_key)


# import os
# from dotenv import load_dotenv
# from langchain_google_genai import ChatGoogleGenerativeAI

# # Load environment variables
# load_dotenv()
# api_key = os.getenv("GEMINI_API_KEY")

# # Initialize Gemini model
# llm = ChatGoogleGenerativeAI(
#     model="gemini-1.5-flash",  # you can also use "gemini-1.5-pro"
#     api_key=api_key
# )



# from langchain_openai import ChatOpenAI
# from dotenv import load_dotenv
# import os
# load_dotenv()
# llm = ChatOpenAI(
#     model="gpt-4o-mini",   # Fast aur sasta model
#     temperature=0.2,
#     api_key=os.getenv("OPEN_API_KEY")  # API key env variable se read karega
# )