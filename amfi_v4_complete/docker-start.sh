#!/bin/bash
# Start AMFI with Docker Compose

echo ""
echo "================================================"
echo "  AMFI v4 - Docker Start"
echo "================================================"
echo ""

# Start services
docker-compose up -d db ollama
echo "Waiting for database..."
sleep 5

# Pull model if not already pulled
echo "Pulling llama3.1 model (first run takes 5-15 min)..."
docker-compose exec ollama ollama pull llama3.1

# Start AMFI
docker-compose up -d amfi

echo ""
echo "================================================"
echo "  AMFI v4 is running!"
echo "  Open: http://localhost:8000"
echo "  Docs: http://localhost:8000/docs"
echo ""
echo "  To stop: docker-compose down"
echo "  Logs:    docker-compose logs -f amfi"
echo "================================================"
echo ""
