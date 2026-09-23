from textual.app import App
from .screens.home import HomeScreen

class BalatroApp(App):
    BINDINGS = [
        ("q", "quit", "退出")
    ]
    
    def __init__(self):
        super().__init__()
        self.game_state = None
    
    def on_mount(self) -> None:
        self.push_screen(HomeScreen())
    
    def action_quit(self):
        self.exit()


if __name__ == "__main__":
    BalatroApp().run()
