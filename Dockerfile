# Use an official lightweight Python image
FROM python:3.13-slim

# Set the working directory in the container
WORKDIR /app

# Copy the requirements file into the container
COPY requirements.txt .

# Install dependencies safely without cache to keep image small
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY . .

# Expose the port Chainlit runs on
EXPOSE 8000

# Command to run the Chainlit application in headless mode
CMD ["chainlit", "run", "app.py", "-h", "--port", "8000"]
