import json
import os

# params/ is a bind-mounted directory and linkedin_searches.txt is git-ignored, so a
# fresh clone starts without it. PUT /api/params/{name} only replaces files that
# already exist, so the API seeds the defaults at startup instead of shipping the file.
DEFAULT_PARAMS = {
    "linkedin_searches": json.dumps(
        {
            "searches": [
                {
                    "Keyword": "Software Engineer",
                    "Location": "Cairo, Egypt",
                    "Experience Level": "Entry level, Associate",
                    "Remote": "Remote, Hybrid, On-Site",
                    "Job Type": "Full-time",
                    "Last Posted": "r604800",
                    "Easy Apply": "",
                }
            ]
        },
        indent=2,
    )
    + "\n",
}


def ensure_default_params(params_dir: str) -> list[str]:
    """Create any missing param file the API owns. Returns the names created."""
    os.makedirs(params_dir, exist_ok=True)
    created = []
    for name, content in DEFAULT_PARAMS.items():
        path = os.path.join(params_dir, f"{name}.txt")
        if not os.path.isfile(path):
            with open(path, "w") as f:
                f.write(content)
            created.append(name)
    return created
