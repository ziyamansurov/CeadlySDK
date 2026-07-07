# Ceadly

Human-in-the-loop governance for enterprise AI agents.

## Install
\`\`\`bash
pip install ceadly
\`\`\`

## Usage
\`\`\`python
from ceadly import guard

@guard(criticality="HIGH")
def transfer_funds(amount: float, account_id: str):
    ...
\`\`\`

Full docs: https://github.com/ziyamansurov/Ceadly