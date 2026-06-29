#!/bin/sh

echo "=== DIAGNOSTIC DES PERMISSIONS ==="
echo "Utilisateur courant : $(id)"
echo "Contenu récursif de /workspace :"
ls -R /workspace

echo "Test d'écriture sur le volume S3..."
if touch /workspace/test_write.txt; then
    echo "[SUCCÈS] Le conteneur peut écrire sur le volume S3 monté dans /workspace."
    rm /workspace/test_write.txt
else
    echo "[ÉCHEC] Impossible d'écrire sur le volume S3 dans /workspace (Permission denied ?)"
fi
echo "=================================="

# Modèles par défaut si non spécifiés
MODEL_NAME=${MODEL_NAME:-"qwen3-coder:30b"}
MODEL_NAME_2=${MODEL_NAME_2:-""}

# Forcer Ollama à écouter localement sur le port interne 11430
export OLLAMA_HOST=127.0.0.1:11430

check_model_presence() {
    local MODEL="$1"
    if [ -z "$MODEL" ]; then
        return 0
    fi
    
    # Extraire le nom du modèle et le tag
    local RAW_MODEL=$(echo "$MODEL" | cut -d: -f1)
    local TAG=$(echo "$MODEL" | cut -d: -f2)
    if [ "$TAG" = "$RAW_MODEL" ]; then
        TAG="latest"
    fi
    
    # Déterminer le chemin du manifest
    local MANIFEST_PATH
    if echo "$RAW_MODEL" | grep -q "/"; then
        MANIFEST_PATH="/workspace/models/manifests/registry.ollama.ai/$RAW_MODEL/$TAG"
    else
        MANIFEST_PATH="/workspace/models/manifests/registry.ollama.ai/library/$RAW_MODEL/$TAG"
    fi
    
    # Vérifier si le modèle est déjà présent dans le volume persistant
    if [ ! -f "$MANIFEST_PATH" ]; then
        echo "❌ ERREUR : Le modèle '$MODEL' n'a pas été trouvé dans le volume persistant !"
        echo "   -> Chemin attendu : $MANIFEST_PATH"
        echo "   -> Rappel : Le téléchargement direct d'un modèle via 'ollama pull' sur un montage S3"
        echo "      ne fonctionne pas chez OVH en raison des verrous/renommagements du système de fichiers."
        echo "   -> Solution : Téléchargez ce modèle sur votre VM de transit (Proxmox), puis uploadez"
        echo "      son contenu ('blobs/' et 'manifests/') dans votre bucket S3 'ollama-storage'."
        exit 1
    else
        echo "✅ Modèle '$MODEL' trouvé dans le stockage persistant."
    fi
}

# Vérifier la présence des modèles requis avant de démarrer
check_model_presence "$MODEL_NAME"
check_model_presence "$MODEL_NAME_2"

# Lancer Ollama en arrière-plan sur localhost:11430
echo "Démarrage du serveur Ollama local sur 127.0.0.1:11430..."
ollama serve &
sleep 8

prewarm_model() {
    local MODEL="$1"
    if [ -z "$MODEL" ]; then
        return
    fi
    # Pré-charger le modèle en mémoire (keep_alive: 5m pour libérer la VRAM si inutilisé)
    echo "Pré-chargement du modèle '$MODEL' en mémoire..."
    curl -s -X POST http://127.0.0.1:11430/api/chat -d "{\"model\": \"$MODEL\", \"messages\": [], \"keep_alive\": \"5m\"}"
    echo ""
}

prewarm_model "$MODEL_NAME"
prewarm_model "$MODEL_NAME_2"
echo "Modèles pré-chargés avec succès !"

# Lancer le proxy de tool-calling sur le port public 11434 (PID 1 du conteneur)
echo "Démarrage du proxy de Tool-calling sur le port public 11434..."
exec python3 /usr/bin/ollama_tool_proxy.py --port 11434 --target http://127.0.0.1:11430