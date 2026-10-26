"""Deterministic fictional labels authored from a controlled vocabulary.

Labels are synthetic author expectations, not independent human judgments.
"""

import json
import copy
from pathlib import Path


def cases():
    pairs = [
        ('Python', 'React'),
        ('PostgreSQL', 'SQLite'),
        ('Docker', 'Terraform'),
        ('FastAPI', 'Django'),
        ('TypeScript', 'Java'),
        ('Redis', 'Elasticsearch'),
        ('PyTorch', 'TensorFlow'),
        ('AWS', 'Azure'),
    ]
    output = []
    for i in range(40):
        a, b = pairs[i % len(pairs)]
        topic = a if (i // len(pairs)) % 2 == 0 else b
        facts = [
            {
                'id': f'fact-{j}',
                'text': f'I built a fictional {tech} service.',
                'project': f'Fictional Project {j}',
                'technologies': [tech],
                'source_reference': f'fictional portfolio {j}',
                'status': 'approved',
                'version': 1,
            }
            for j, tech in enumerate((a, b, 'Rust', 'Go'))
        ]
        facts += [
            {
                'id': 'unapproved',
                'text': f'I led a fictional {topic} team.',
                'project': 'Fictional Unverified',
                'technologies': [topic],
                'source_reference': 'unverified',
                'status': 'draft',
                'version': 1,
            },
            {
                'id': 'retired',
                'text': f'I maintained a fictional {topic} system.',
                'project': 'Fictional Retired',
                'technologies': [topic],
                'source_reference': 'retired',
                'status': 'retired',
                'version': 1,
            },
        ]
        description = f'Required: build services using {topic}.\nPreferred: accessibility audits.'
        output.append(
            {
                'id': f'fictional-{i:02}',
                'role': 'Software Engineer',
                'company': f'Fictional Company {i}',
                'description': description,
                'facts': facts,
                'contacts': [
                    {
                        'id': 'recruiter',
                        'title': 'Technical Recruiter',
                        'evidence': f'Avery Example recruits engineers at Fictional Company {i}.',
                    },
                    {
                        'id': 'unrelated',
                        'title': 'Accountant',
                        'evidence': f'Robin Example is an accountant at Fictional Company {i}.',
                    },
                ],
                'expected_fact_ids': ['fact-0' if topic == a else 'fact-1'],
                'expected_contact_ids': ['recruiter'],
                'expected_unsupported': ['accessibility audits'],
                'label_origin': 'synthetic controlled-vocabulary expectations',
            }
        )
    aliases = {'Go': 'golang', 'React': 'React.js', 'Python': 'Python3', 'PostgreSQL': 'Postgres'}
    for i, case in enumerate(output):
        primary = next(f for f in case['facts'] if f['id'] == case['expected_fact_ids'][0])
        tech = primary['technologies'][0]
        case['description'] = (
            f"Required: Design and maintain dependable customer-facing services using {aliases.get(tech,tech)}; review changes and investigate service incidents.\nPreferred: Kubernetes deployment experience.\nCollaborate with product teams to clarify delivery requirements and document operational decisions."
        )
        case['expected_unsupported'] = ['Kubernetes deployment experience']
        case['label_origin'] = (
            'synthetic author-assigned explicit technology evidence; not independent human judgments'
        )
        if i % 5 == 0:
            case['role'] = (
                'Senior Software Engineer, Customer Platform and Distributed Application Infrastructure'
            )
    for i in range(10):
        case = copy.deepcopy(output[i])
        old_company = case['company']
        case['id'] = f'fictional-expanded-{i:02}'
        case['company'] = f'Fictional Harbor Research {i}'
        tech = case['facts'][0]['technologies'][0]
        case['description'] = (
            f"Required: Design and maintain dependable customer-facing services using {aliases.get(tech,tech)}; review changes and investigate service incidents.\nPreferred: Kubernetes deployment experience.\nCollaborate with product teams to clarify delivery requirements and document operational decisions."
        )
        case['description'] += (
            '\nRequired: '
            + case['facts'][1]['technologies'][0]
            + ' for internal tools and reusable application components.\nPreferred: Helm chart maintenance with peer-reviewed changes.'
        )
        case['expected_fact_ids'] = ['fact-0', 'fact-1']
        case['expected_unsupported'].append('Helm chart maintenance')
        case['facts'].append(
            {
                'id': 'generic-service',
                'text': 'I develop fictional services using COBOL.',
                'project': 'Unrelated example',
                'technologies': ['COBOL'],
                'source_reference': 'fictional service notes',
                'status': 'approved',
                'version': 1,
            }
        )
        for contact in case['contacts']:
            contact['evidence'] = contact['evidence'].replace(old_company, case['company'])
        case['contacts'] += [
            {
                'id': 'manager',
                'title': 'Engineering Manager, Customer Platform and Developer Infrastructure',
                'evidence': f"Taylor Fictional is Engineering Manager, Customer Platform and Developer Infrastructure at {case['company']}.",
            },
            {
                'id': 'former',
                'title': 'Former Technical Recruiter',
                'evidence': f"Casey Fictional previously recruited at {case['company']} and now works elsewhere.",
            },
        ]
        case['expected_contact_ids'] = ['recruiter', 'manager']
        output.append(case)
    return output


if __name__ == '__main__':
    Path('evaluation/cases.json').write_text(json.dumps(cases(), indent=2) + '\n')
