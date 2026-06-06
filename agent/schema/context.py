from dataclasses import dataclass
from datetime import datetime


@dataclass
class Context:
    user_name: str
    current_time: datetime
