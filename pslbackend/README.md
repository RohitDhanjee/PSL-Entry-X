<!-- How to Run the DRM Backend Project 
This guide provides step-by-step instructions for setting up and running the DRM backend 
service locally. Please follow the instructions carefully to ensure proper setup and execution. 
Project Repository 
GitHub Repo: https://github.com/aiprojects789/drmbackend/tree/main 
Branch: main 
Prerequisites 
Ensure the following are installed on your local machine: 
● Python 3.9+ 
● pip (Python package installer) 
● Git 
● A virtual environment tool (e.g., venv, virtualenv, or conda) 
● Internet access to download dependencies 
Setup Instructions 
1. Clone the Repository 
git clone https://github.com/aiprojects789/drmbackend.git 
cd drmbackend 
git checkout main 
2. Create a Virtual Environment (Optional but Recommended) 
# For Linux/macOS 
python3 -m venv venv 
source venv/bin/activate 
# For Windows 
python -m venv venv 
venv\Scripts\activate 
3. Install Dependencies 
pip install -r requirements.txt 
4. Configure Environment Variables 
Create a .env file in the root directory (drmbackend) with the following content: 
MONGODB_URI=mongodb+srv://aiprojects789:IP1NwVwaBM0TosQI@drm.cmnzpag.m
 ongodb.net/art_drm?retryWrites=true&w=majority&tls=true 
DB_NAME=art_drm_local 
JWT_SECRET_KEY=Ethical_DRM 
JWT_ALGORITHM=HS256 
ACCESS_TOKEN_EXPIRE_MINUTES=30 
IPFS_API_KEY= 
IPFS_API_SECRET= 
WEB3_PROVIDER_URL=https://polygon-rpc.com 
CONTRACT_ADDRESS= 
Note: 
● Keep this file secure and do not commit it to version control. 
5. Run the Development Server 
uvicorn app.main:app --reload 
The server will start at http://127.0.0.1:8000 
API Documentation 
Once the server is running, you can access interactive API docs at: 
● Swagger UI: http://127.0.0.1:8000/docs 
● ReDoc: http://127.0.0.1:8000/redoc  -->