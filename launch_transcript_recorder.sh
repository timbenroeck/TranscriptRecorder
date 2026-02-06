#!/usr/bin/env zsh
set -e  # exit on any error

SCRIPT_DIR=${0:a:h}
SCRIPT_PATH=${0:a}
VENV_DIR="$SCRIPT_DIR/.venv"

# Move into the project directory
cd "$SCRIPT_DIR"

# If .venv doesn't exist, create it and install requirements
if [ ! -d "$VENV_DIR" ]; then
  echo "Creating virtual environment in $VENV_DIR…"
  python3 -m venv $VENV_DIR
  echo "Activating virtual environment and installing dependencies…"
  # shellcheck disable=SC1091
  source $VENV_DIR/bin/activate
  pip install --upgrade pip
  pip install -r requirements.txt

  # Check if the alias is already in .zshrc; if not, add it
  if ! grep -q "alias grecorder=" ~/.zshrc; then
    echo "\n# Added by transcript recorder setup" >> ~/.zshrc
    echo "alias grecorder='$SCRIPT_PATH'" >> ~/.zshrc
    echo "✅ Alias 'recorder' added to ~/.zshrc. Restart terminal or run 'source ~/.zshrc' to use it."
  else
    echo "ℹ️ Alias 'recorder' already exists in ~/.zshrc."
  fi

else
  echo "Virtual environment found. Activating…"
  # shellcheck disable=SC1091
  source $VENV_DIR/bin/activate
fi

# Run your GUI app
echo "Running gui_app.py…"
python gui_app.py

