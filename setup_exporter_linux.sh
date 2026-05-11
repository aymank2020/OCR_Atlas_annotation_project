#!/bin/bash
# setup_exporter_linux.sh: Setup DiscordChatExporter.Cli on Ubuntu VPS

echo "🚀 Starting Atlas Exporter Setup (Linux)..."

# 1. Install .NET Runtime 8.0 (Current LTS recommended)
echo "📥 Installing .NET Runtime..."
sudo apt-get update
sudo apt-get install -y dotnet-runtime-8.0 wget unzip

# 2. Create directory for Exporter
EXPORT_DIR="$HOME/atlas_exporter"
rm -rf "$EXPORT_DIR" # Clean start
mkdir -p "$EXPORT_DIR"
cd "$EXPORT_DIR"

# 3. Download Latest DiscordChatExporter.Cli (Linux-x64)
# Using wget for better redirect handling
echo "📥 Downloading DiscordChatExporter.Cli..."
# NOTE: The asset name uses a DOT before linux-x64, not an underscore.
URL="https://github.com/Tyrrrz/DiscordChatExporter/releases/latest/download/DiscordChatExporter.Cli.linux-x64.zip"
wget -O DiscordChatExporter.Cli.zip "$URL"

# 4. Unzip
echo "📦 Unzipping..."
unzip -o DiscordChatExporter.Cli.zip
chmod +x DiscordChatExporter.Cli

# 5. Create Alias logic
echo "📎 Setting up alias..."
ALIAS_CMD="alias atlas-export='$EXPORT_DIR/DiscordChatExporter.Cli'"
if ! grep -q "atlas-export" ~/.bashrc; then
    echo "$ALIAS_CMD" >> ~/.bashrc
    echo "✅ Alias 'atlas-export' added to ~/.bashrc"
fi

echo "--------------------------------------------------"
echo "✅ Setup Complete!"
echo "🔄 Run 'source ~/.bashrc' to enable the 'atlas-export' command."
echo "👉 Usage: atlas-export export -t \"YOUR_TOKEN\" -c \"CHANNEL_ID\" -o \"history.json\" -f Json"
echo "--------------------------------------------------"
