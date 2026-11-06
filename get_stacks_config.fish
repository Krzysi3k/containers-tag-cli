#!/usr/bin/env fish

set output /home/krzysiek/automation/docker-tags-cli/stacks_config.json

# project working dir -> compose config files, for every running compose project
set projects (docker inspect (docker ps --format '{{.Names}}') | jq -r '
    map(select(.Config.Labels["com.docker.compose.project.working_dir"] != null)
        | [.Config.Labels["com.docker.compose.project.working_dir"],
           .Config.Labels["com.docker.compose.project.config_files"]]
        | @tsv)
    | unique | .[]')

set entries
for project in $projects
    set parts (string split \t -- $project)
    set workdir $parts[1]
    set files (string split , -- $parts[2])

    set args
    for f in $files
        set args $args -f $f
    end

    # only images declared in the compose files (no `image:` => skipped)
    docker compose --project-directory $workdir $args config --format json 2>/dev/null \
        | jq --arg dir $workdir '[.services[] | select(.image != null) | {key: (.image | sub(":[^:/]*$"; "")), value: $dir}]' \
        | read -z -l json
    set entries $entries $json
end

printf '%s\n' $entries | jq -s 'add // [] | from_entries' > $output
