from InquirerPy import prompt
from dataclasses import dataclass



@dataclass
class ImageTag:
    image_name: str
    tags: list[str]
    current_tag: str


class QuestionFlow:
    
    def __init__(self, image_tags: list[ImageTag]):
        questions = [
        {
            "message": "select image",
            "type": "fuzzy",
            "choices": [ t.image_name for t in image_tags ],
            "max_height": "30%",
            "name": "image_step"
        },
        {
            "message": "select new tag",
            "type": "fuzzy",
            "choices": lambda result: [ tag for i in image_tags if i.image_name == result["image_step"] for tag in i.tags ],
            "multiselect": False,
            "max_height": "30%",
            "name": "tag_step",
        },
        {
            "message": "apply new tag to .env file?",
            "type": "confirm",
            "default": True,
            "name": "apply_step",
        },
        {
            "message": "choose stack",
            "type": "list",
            "choices": ["homestack","chatops","go back", "cancel"],
            "name": "stack_step",
            "default": "cancel",
            "when": lambda result: result["apply_step"]
        }]
        result = prompt(
            questions,
            style={"questionmark": "#ff9d00 bold"},
            vi_mode=True,
            style_override=False,
        )
        _ = [ result.update({'current_tag': i.current_tag}) for i in image_tags if result['image_step'] == i.image_name ]
        self.result = result
