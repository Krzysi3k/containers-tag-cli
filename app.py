from rich.console import Console
from rich import box
from rich.table import Table
from pathlib import Path
import docker
import requests
from subprocess import Popen, PIPE, CalledProcessError
from question_flow import QuestionFlow
from question_flow import ImageTag
from dotenv import load_dotenv
from InquirerPy import inquirer
import os
import json
import shutil


client = docker.from_env()
load_dotenv()
env_file = {
    'homestack': os.environ['HOMESTACK_DOTENV_PATH'],
    'chatops': os.environ['CHATOPS_DOTNEV_PATH']
}


def get_images() -> list[str]:
    os.system('clear')
    console = Console()
    table = Table(show_header=True, header_style="bold magenta", box=box.HEAVY)
    table.add_column("Nr")
    table.add_column("Image")
    table.add_column("Current Tag")

    row_num = 1
    images = []
    _ = [ images.extend(i.tags) for i in client.images.list() ]
    sorted_imgs = sorted(images)
    for image in sorted_imgs:
        table.add_row(f"{row_num}", image.split(":")[0], image.split(":")[1])
        row_num += 1

    console.print(table)
    return sorted_imgs


def fetch_tags(images: list[str], page_size=100) -> list[ImageTag]:
    ignored_file = str(Path(__file__).parent) + '/.imageignore'
    with open(ignored_file, 'r') as ignored_file:
        images_ignored = ignored_file.read().split('\n')
    console = Console()
    image_tags = []
    with console.status('[bold green]fetching image tags...[/bold green]', spinner='dots2') as spn:
        for image in images:
            image_library = image.split(':')[0]
            if image_library in images_ignored:
                continue
            if '/' not in image_library:
                image_library = f'library/{image_library}'
            api_url = f'https://hub.docker.com/v2/repositories/{image_library}/tags?page_size={page_size}'
            r = requests.get(api_url)
            content = json.loads(r.content)
            tags = [ i['name'] for i in content['results'] ]
            img_name, curr_tag = image.split(':')
            image_tags.append(
                ImageTag(
                    image_name=img_name,
                    tags=tags,
                    current_tag=curr_tag
                )
            )
    return image_tags


def replace_tags(old_tag: str, new_tag: str, stack_name: str):
    env_path = env_file.get(stack_name, None)
    if env_file:
        print(f'replacing tag: {old_tag} --> {new_tag}')
        shutil.copyfile(f'{env_path}/.env', f'{env_path}/.bckp_env')
        with open(f'{env_path}/.env', 'r') as f:
            content = f.read()
        new_content = content.replace(f'={old_tag}', f'={new_tag}')
        with open(f'{env_path}/.env', 'w+') as f:
            f.write(new_content)


def main():
    images = get_images()
    q = inquirer.confirm(message='fetch new tags?', default=True).execute()
    if not q:
        os._exit(0)
    image_tags = fetch_tags(images)

    qf = QuestionFlow(image_tags)
    while qf.result['stack_step'] is None or qf.result['stack_step'] == 'go back':
        qf = QuestionFlow(image_tags)
    
    if qf.result['stack_step'] == 'cancel':
        os._exit(0)

    if qf.result['apply_step']:
        replace_tags(
            qf.result['current_tag'],
            qf.result['tag_step'],
            qf.result['stack_step']
        )
    if qf.result['stack_step'] != 'cancel':
        q_reload = inquirer.confirm(message='reload stack', default=True).execute()
        if q_reload:
            work_dir = env_file.get(qf.result['stack_step'], None)
            if work_dir:
                print('reloading containers...')
                os.chdir(work_dir)
                #Popen(['sh', f'{work_dir}/restart.sh'], stdout=PIPE, stderr=PIPE).communicate()
                with Popen(['sh',  f'{work_dir}/restart.sh'], stdout=PIPE, bufsize=1, universal_newlines=True) as p:
                    for line in p.stdout:
                        print(line, end='')
                if p.returncode != 0:
                    raise CalledProcessError(p.returncode, p.args)

if __name__ == '__main__':
    main()
