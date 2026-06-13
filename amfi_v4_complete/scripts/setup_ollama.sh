#!/bin/bash
# AMFI v4 - Ollama Setup Script
# Run this on your Linux server to install Ollama and pull the model

echo ""
echo "================================================"
echo "  AMFI v4 - Ollama Setup"
echo "================================================"
echo ""

# Check if running on Linux
if [[ "$OSTYPE" != "linux-gnu"* ]]; then
    echo "This script is for Linux. For Windows:"
    echo "  1. Download Ollama from https://ollama.ai"
    echo "  2. Install it"
    echo "  3. Run: ollama pull llama3.1"
    exit 0
fi

# Install Ollama
echo "Installing Ollama..."
curl -fsSL https://ollama.ai/install.sh | sh

if [ $? -ne 0 ]; then
    echo "Ollama installation failed. Please install manually from https://ollama.ai"
    exit 1
fi

echo "Ollama installed successfully"
echo ""

# Start Ollama service
echo "Starting Ollama service..."
systemctl enable ollama 2>/dev/null || true
systemctl start  ollama 2>/dev/null || ollama serve &
sleep 3

# Pull the model
echo "Pulling llama3.1 model (~4.7GB)..."
echo "This will take 5-15 minutes depending on your connection."
echo ""
ollama pull llama3.1

if [ $? -ne 0 ]; then
    echo "Model pull failed. Try manually: ollama pull llama3.1"
    exit 1
fi

echo ""
echo "Verifying model..."
ollama list | grep llama3.1

echo ""
echo "================================================"
echo "  Ollama setup complete!"
echo "  Model: llama3.1"
echo "  Running on: http://localhost:11434"
echo ""
echo "  Now start AMFI: python run.py"
echo "================================================"
echo ""
