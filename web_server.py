"""
Flask Web Server for Chess Control Panel.
Provides a mobile-friendly interface to control the chess game from a second phone.
"""
from flask import Flask, render_template, jsonify, request
import threading
import time

# Create Flask app
app = Flask(__name__)

# Shared state - will be set by gui_app.py
game_state = {
    'status': 'Idle',
    'is_my_turn': False,
    'my_color': 'white',
    'game_id': None,
    'my_time': 600,  # 10 minutes in seconds
    'opponent_time': 600,
    'moves': [],
    'camera_connected': False,
    'lichess_connected': False,
    'last_opponent_move': None,
}

# Reference to the main app (set by gui_app.py)
main_app = None


@app.route('/')
def control_panel():
    """Serve the mobile control panel."""
    return render_template('control_panel.html')


@app.route('/api/status')
def get_status():
    """Return current game status as JSON."""
    return jsonify(game_state)


@app.route('/api/new_game', methods=['POST'])
def new_game():
    """Start a new game."""
    if main_app:
        data = request.json or {}
        level = data.get('level', 3)
        color = data.get('color', 'white')
        # Call the main app's new game method
        try:
            main_app.start_new_game_from_web(level, color)
            return jsonify({'success': True, 'message': f'Starting new game (Level {level})'})
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)})
    return jsonify({'success': False, 'message': 'Main app not connected'})


@app.route('/api/reset_baseline', methods=['POST'])
def reset_baseline():
    """Force baseline recapture."""
    if main_app:
        try:
            main_app.force_reset_baseline()
            return jsonify({'success': True, 'message': 'Baseline reset requested'})
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)})
    return jsonify({'success': False, 'message': 'Main app not connected'})


@app.route('/api/resign', methods=['POST'])
def resign():
    """Resign current game."""
    if main_app:
        try:
            main_app.resign_game_from_web()
            return jsonify({'success': True, 'message': 'Game resigned'})
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)})
    return jsonify({'success': False, 'message': 'Main app not connected'})


def update_game_state(new_state: dict):
    """Update the shared game state (called by gui_app.py)."""
    global game_state
    game_state.update(new_state)


def start_server(host='0.0.0.0', port=5000):
    """Start the Flask server in a background thread."""
    def run():
        # Suppress Flask's default logging for cleaner output
        import logging
        log = logging.getLogger('werkzeug')
        log.setLevel(logging.ERROR)
        
        print(f"\n=== Web Control Panel ===")
        print(f"Access from your phone at: http://YOUR-PC-IP:{port}")
        print(f"(Find your IP with 'ipconfig' in Command Prompt)")
        print(f"=========================\n")
        
        app.run(host=host, port=port, threaded=True, use_reloader=False)
    
    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread


def set_main_app(app_instance):
    """Set reference to main GUI app."""
    global main_app
    main_app = app_instance


if __name__ == '__main__':
    # Test run
    print("Starting test server...")
    app.run(host='0.0.0.0', port=5000, debug=True)
