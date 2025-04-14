from InquirerPy import inquirer
from dataclasses import dataclass

@dataclass
class ImageTag:
    image_name: str
    tags: list[str]
    current_tag: str

class QuestionFlow:
    
    def __init__(self, image_tags: list[ImageTag]):
        # Get image selection
        image_step = inquirer.fuzzy(
            message="select image",
            choices=[t.image_name for t in image_tags],
            max_height="30%"
        ).execute()
        
        # Get tag selection
        selected_image_tags = [tag for i in image_tags if i.image_name == image_step for tag in i.tags]
        tag_step = inquirer.fuzzy(
            message="select new tag",
            choices=selected_image_tags,
            multiselect=False,
            max_height="30%"
        ).execute()
        
        # Apply tag confirmation
        apply_step = inquirer.confirm(
            message="apply new tag to .env file?",
            default=True
        ).execute()
        
        # Stack selection if applying
        stack_step = None
        if apply_step:
            stack_step = inquirer.select(
                message="choose stack",
                choices=["homestack", "chatops", "wireguard", "go back", "cancel"],
                default="cancel"
            ).execute()
        
        # Construct result dictionary
        self.result = {
            "image_step": image_step,
            "tag_step": tag_step,
            "apply_step": apply_step,
            "stack_step": stack_step
        }
        
        # Add current_tag to result
        for i in image_tags:
            if self.result['image_step'] == i.image_name:
                self.result['current_tag'] = i.current_tag
                break
