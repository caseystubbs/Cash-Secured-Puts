# Use the official Python 3.9 image (Stable & Reliable)
FROM python:3.9-slim

# Set the working directory inside the container
WORKDIR /app

# Copy requirements and install them
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of your app code
COPY . .

# Run the app using Railway's PORT variable
CMD sh -c "streamlit run app.py --server.port=$PORT --server.address=0.0.0.0"