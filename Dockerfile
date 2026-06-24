FROM ollama/ollama:latest

# Création des dossiers requis avec les droits pour l'utilisateur OVH (42420)
RUN mkdir -p /workspace /tmp/.ollama && \
    chown -R 42420:42420 /workspace /tmp /tmp/.ollama

# Variables d'environnement intégrées à l'image
ENV HOME=/tmp
ENV OLLAMA_MODELS=/workspace/models
ENV OLLAMA_HOST=0.0.0.0

# Exposition du port par défaut d'Ollama
EXPOSE 11434

# Forcer l'utilisation de l'utilisateur non-root d'OVHcloud
USER 42420:42420

ENTRYPOINT ["/bin/ollama"]
CMD ["serve"]
