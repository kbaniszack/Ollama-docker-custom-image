#!/bin/sh

# Vérifier si le répertoire du modèle existe dans le volume persistant
# Ollama range les modèles dans des sous-dossiers, on vérifie la présence du modèle
if [ ! -d "/workspace/models/manifests/registry.ollama.ai/library/qwen3-coder" ]; then
    echo "Modèle non trouvé, téléchargement en cours..."
    # Lancer ollama serve en arrière-plan pour le pull
    ollama serve &
    # Attendre que le serveur soit prêt
    sleep 10 
    # Télécharger le modèle (le nom doit correspondre exactement au repo Ollama)
    ollama pull qwen3-coder:30b
    # Arrêter le serveur temporaire pour redémarrer proprement
    pkill ollama
    sleep 2
fi

# Lancer Ollama normalement
echo "Démarrage du serveur Ollama..."
exec ollama serve