"""
Text-to-Speech Engine for announcing chess moves and game events.
"""
import subprocess
import threading
import queue
import time

class TTSEngine:
    """
    Robust Text-to-Speech using Windows PowerShell.
    Serialized via a queue to prevent overlapping voices.
    """
    
    def __init__(self, rate: int = None, voice: str = None):
        self.speech_queue = queue.Queue()
        self.is_running = True
        # Start the worker thread
        threading.Thread(target=self._worker, daemon=True).start()
    
    def say(self, text: str) -> None:
        """Add text to the speech queue."""
        self.speech_queue.put(text)
        
    def _worker(self):
        """Consume messages from queue and speak them one by one."""
        while self.is_running:
            try:
                text = self.speech_queue.get()
                self._speak_subprocess(text)
                self.speech_queue.task_done()
            except Exception as e:
                print(f"TTS Worker Error: {e}")

    def _speak_subprocess(self, text: str):
        """Run the PowerShell command to speak."""
        try:
            # Escape quotes for PowerShell
            safe_text = text.replace('"', "'").replace("'", "''")
            cmd = f'Add-Type -AssemblyName System.Speech; $synth = New-Object System.Speech.Synthesis.SpeechSynthesizer; $synth.Speak("{safe_text}");'
            
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            
            # This blocks until speech finishes
            subprocess.run(["powershell", "-Command", cmd], 
                         startupinfo=startupinfo,
                         creationflags=subprocess.CREATE_NO_WINDOW)
        except Exception as e:
            print(f"TTS Error: {e}")

    def announce_color(self, is_white: bool) -> None:
        color = "White" if is_white else "Black"
        self.say(f"You are {color}")
    
    def announce_move(self, san: str) -> None:
        spoken = self._expand_notation(san)
        self.say(spoken)
    
    def announce_game_start(self) -> None:
        self.say("Game started")
    
    def announce_game_end(self, result: str, reason: str = None) -> None:
        self.say(f"Game over. Result is {result}")
    
    def announce_your_turn(self) -> None:
        self.say("Your turn. Make your move.")
    
    def _expand_notation(self, san: str) -> str:
        # Expand piece names
        san = san.replace("N", "Knight ").replace("B", "Bishop ").replace("R", "Rook ").replace("Q", "Queen ").replace("K", "King ")
        san = san.replace("x", " takes ").replace("O-O-O", "Castles queenside").replace("O-O", "Castles kingside")
        san = san.replace("+", " check").replace("#", " checkmate")
        
        # Spell out file letters for better pronunciation
        # e.g., "a6" -> "A 6", "e4" -> "E 4"
        result = []
        i = 0
        while i < len(san):
            char = san[i]
            # If this is a file letter (a-h) followed by a rank number
            if char.lower() in 'abcdefgh' and i + 1 < len(san) and san[i + 1].isdigit():
                result.append(char.upper())  # "a" -> "A"
                result.append(' ')
                result.append(san[i + 1])    # "6"
                i += 2
            else:
                result.append(char)
                i += 1
        
        return ''.join(result)

if __name__ == "__main__":
    tts = TTSEngine()
    print("Testing PowerShell TTS...")
    tts.say("First line.")
    tts.say("Second line should wait for first.")
    time.sleep(5)
