from pydantic import BaseModel


class PatentDoc(BaseModel):
    application_number: str
    title: str
    abstract: str
    claims: dict[int, str]            # {1: "웨트 마스터 배치...", ...}
    spec_paragraphs: dict[str, str]   # {"0001": "본 발명은...", ...}


class PriorArtDoc(PatentDoc):
    prior_art_id: str                 # "인용발명1"
    publication_number: str


class OfficeActionRaw(BaseModel):
    application_number: str
    raw_dict: dict
