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
from yaspin.spinners import Spinners
from yaspin import yaspin
from tabulate import tabulate


client = docker.from_env()
load_dotenv()
env_file = {
    'homestack': os.environ['HOMESTACK_DOTENV_PATH'],
    'chatops': os.environ['CHATOPS_DOTNEV_PATH'],
    'wireguard': os.environ['ALWAYS_ON_SERVICES']
}


def get_images() -> list[str]:
    os.system('clear')
    images = []
    _ = [ images.extend(i.tags) for i in client.images.list() ]
    sorted_imgs = sorted(images)

    # Load stacks config
    stacks_config_path = str(Path(__file__).parent / 'stacks_config.json')
    with open(stacks_config_path, 'r') as f:
        stacks_config = json.load(f)

    rows = []
    for idx, image in enumerate(sorted_imgs):
        image_name = image.split(":")[0]
        current_tag = image.split(":")[1]
        stack_name = "-"
        for key, path in stacks_config.items():
            if key in image_name or image_name in key:
                stack_name = path.split('/')[-1]
                break
        rows.append(
            [ f"{idx+1}", image_name, current_tag, stack_name ]
        )
    print(tabulate(rows, headers=["Nr", "Image", "Current Tag", "Stack"], tablefmt="psql"))
    return sorted_imgs


def fetch_tags(images: list[str], page_size=100) -> list[ImageTag]:
    ignored_file = str(Path(__file__).parent) + '/.imageignore'
    with open(ignored_file, 'r') as ignored_file:
        images_ignored = ignored_file.read().split('\n')
    image_tags = []
    with yaspin(Spinners.sand, text="") as sp:
        for image in images:
            image_library = image.split(':')[0]
            if image_library in images_ignored:
                continue
            if '/' not in image_library:
                image_library = f'library/{image_library}'
            sp.color, sp.text = 'white', f'fetching tags for: {image_library}'
            if 'ghcr.io' in image_library:
                image_library = image.split('/')[1]
                r = requests.get(f'https://api.github.com/repos/{image_library}/{image_library}/tags?per_page=100')
                content = json.loads(r.content)
                tags = [ i['name'] for i in content ]
            else:
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
        q_pull = inquirer.confirm(message='pull new image?', default=True).execute()
        if q_pull:
            image_with_tag = f"{qf.result['image_step']}:{qf.result['tag_step']}"
            print(f'pulling image: {image_with_tag}...')
            with yaspin(Spinners.sand, text=f"Pulling {image_with_tag}") as sp:
                try:
                    with Popen(['docker', 'pull', image_with_tag], stdout=PIPE, stderr=PIPE, bufsize=1, universal_newlines=True) as p:
                        for line in p.stdout:
                            sp.text = f"Pulling {image_with_tag}: {line.strip()}"
                    
                    # Check if image exists after download using docker image inspect
                    inspect_process = Popen(['docker', 'image', 'inspect', image_with_tag], 
                                        stdout=PIPE, stderr=PIPE, universal_newlines=True)
                    inspect_output, inspect_error = inspect_process.communicate()
                    
                    if inspect_process.returncode == 0:
                        sp.ok("✅ ")
                        print(f"Successfully pulled and verified {image_with_tag}")
                    else:
                        sp.fail("❌ ")
                        print(f"Failed to verify image: {inspect_error.strip()}")
                        
                except Exception as e:
                    sp.fail("❌ ")
                    print(f"Error pulling image: {str(e)}")

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
    try:
        main()
    except KeyboardInterrupt:
        os._exit(0)
