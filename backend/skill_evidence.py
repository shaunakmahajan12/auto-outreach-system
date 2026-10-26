"""Conservative named-skill recognition. Similarity is discovery, never proof."""

import re

ALIASES = {
    'kubernetes': ('kubernetes', 'k8s'),
    'python': ('python', 'python3'),
    'javascript': ('javascript', 'js', 'ecmascript'),
    'typescript': ('typescript', 'ts'),
    'react': ('react', 'reactjs', 'react.js'),
    'node.js': ('node.js', 'nodejs'),
    'postgresql': ('postgresql', 'postgres', 'psql'),
    'sql': ('sql',),
    'docker': ('docker',),
    'aws': ('aws', 'amazon web services'),
    'azure': ('azure',),
    'gcp': ('gcp', 'google cloud'),
    'terraform': ('terraform',),
    'java': ('java',),
    'c++': ('c++', 'cpp'),
    'c#': ('c#', 'csharp'),
    'golang': ('golang', 'go'),
    'rust': ('rust',),
    'redis': ('redis',),
    'django': ('django',),
    'helm': ('helm',),
    'kafka': ('kafka',),
    'sqlite': ('sqlite',),
    'fastapi': ('fastapi',),
    'pytorch': ('pytorch',),
    'tensorflow': ('tensorflow',),
    'graphql': ('graphql',),
    'elasticsearch': ('elasticsearch', 'elastic search'),
    'mongodb': ('mongodb', 'mongo'),
    'ci/cd': ('ci/cd', 'continuous integration', 'continuous delivery'),
    'accessibility': ('accessibility', 'a11y', 'wcag'),
    'linux': ('linux',),
    'machine learning': ('machine learning', 'ml'),
    'langgraph': ('langgraph',),
}
# Ordinary phrases that reuse a short alias; removed before that skill is matched.
NOT_SKILLS = {
    'helm': r'\b(?:at|take|takes|took|taking) the helm\b',
    'typescript': r'\bts/sci\b',
    'machine learning': r'\b\d+(?:\.\d+)?\s*ml\b',
}


def skills(value):
    value = value.casefold()
    found = set()
    for name, aliases in ALIASES.items():
        # A framework name containing .js does not independently prove JavaScript.
        target = re.sub(r'\b(?:react|node)\.js\b', '', value) if name == 'javascript' else value
        if name == 'golang':
            target = (
                re.sub(r'\bgo\b', '', target)
                if not re.search(
                    r'\b(?:using|in|with) go\b|\bgo (?:service|language|application|project)\b',
                    target,
                )
                else target
            )
        if name in NOT_SKILLS:
            target = re.sub(NOT_SKILLS[name], '', target)
        if any(
            re.search(r'(?<![\w+#])' + re.escape(alias) + r'(?![\w+#])', target)
            for alias in aliases
        ):
            found.add(name)
    return found
