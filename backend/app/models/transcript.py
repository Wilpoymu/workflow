from pydantic import BaseModel


class WhisperWord(BaseModel):
    text: str
    start: float
    end: float
    type: str = "word"
    speaker_id: str = "speaker_0"
    logprob: float = 0


class TranscriptionSegment(BaseModel):
    language_code: str = "es"
    language_probability: float = 1.0
    text: str = ""
    words: list[WhisperWord] = []


class SrtBlock(BaseModel):
    index: int
    start: float
    end: float
    text: str
