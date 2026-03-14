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
    ignored_file_path = Path(__file__).parent / '.imageignore'
    with open(ignored_file_path, 'r') as f:
        images_ignored = f.read().splitlines()
    image_tags = []
    with yaspin(Spinners.sand, text="") as sp:
        for image in images:
            img_name, curr_tag = image.split(':')

            # Skip ignored images
            if img_name in images_ignored:
                continue

            # Determine where to fetch tags from
            if 'ghcr.io' in img_name:
                # GHCR image format: ghcr.io/owner/repo
                # Strip 'ghcr.io/' prefix
                path = img_name.split('/', 1)[1]  # owner/repo
                sp.color, sp.text = 'white', f'fetching container registry tags for: {img_name}'

                # Fetch tags from GHCR Docker registry API
                # API docs: https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry#listing-image-tags
                # GHCR registry API for tags: https://ghcr.io/v2/{owner}/{repo}/tags/list

                url = f'https://ghcr.io/v2/{path}/tags/list'
                r = requests.get(url)
                if r.status_code == 200:
                    content = r.json()
                    tags = content.get('tags', [])
                    if not tags:
                        # fallback to git tags if container tags are empty
                        # sp.text = f'No container tags for {img_name}, fetching git tags...'
                        owner, repo = path.split('/')
                        git_url = f'https://api.github.com/repos/{owner}/{repo}/tags?per_page=100'
                        r2 = requests.get(git_url)
                        if r2.status_code == 200:
                            git_tags = [tag['name'] for tag in r2.json()]
                            tags = git_tags
                        else:
                            tags = []
                else:
                    # fallback to git tags if request failed
                    # sp.text = f'Failed container registry request for {img_name}, fetching git tags...'
                    owner, repo = path.split('/')
                    git_url = f'https://api.github.com/repos/{owner}/{repo}/tags?per_page=100'
                    r2 = requests.get(git_url)
                    if r2.status_code == 200:
                        tags = [tag['name'] for tag in r2.json()]
                    else:
                        tags = []
            else:
                # For non-GHCR images, get from Docker Hub API
                if '/' not in img_name:
                    image_library = f'library/{img_name}'
                else:
                    image_library = img_name
                sp.color, sp.text = 'white', f'fetching tags for: {image_library}'
                api_url = f'https://hub.docker.com/v2/repositories/{image_library}/tags?page_size={page_size}'
                r = requests.get(api_url)
                if r.status_code == 200:
                    content = r.json()
                    tags = [i['name'] for i in content.get('results', [])]
                else:
                    tags = []

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
