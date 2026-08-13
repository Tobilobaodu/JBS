# Cover letter generation schema and decision process

This document describes a comprehensive pattern and decision process for generating short, email style cover letters in code. It blends practical guidance from hiring managers, modern job search practice, StandOut CV style short letters, Reddit practitioner advice and Harvard career services guidance.

The goal is to produce a script that takes structured inputs, decides how strongly to lean on experience versus potential, and outputs a concise, tailored cover letter that feels human and specific.

## Design goals

- Always relate directly to a specific job description and employer.
- Keep the letter short (roughly 150–300 words, or 3–4 short paragraphs) and easy to scan.
- Make the letter a persuasive mini interview that answers:
  - Why you want this job.
  - Why they should hire you.
- Use at least one concrete, quantified achievement.
- Maintain a friendly but professional voice and avoid flowery or generic language.

## Required inputs

The script should expect structured inputs rather than free text. At minimum:

### Job data

- `job_title`: role title.
- `company_name`: employer name.
- `application_source`: where you saw the posting (site, referral, etc.).
- `key_responsibilities`: list of 3–5 short phrases taken from the "What you will do" or equivalent section of the job description.

### User profile

- `candidate_name`: full name.
- `current_role`: current or most recent role title.
- `field_or_title`: short description of field (for example "software engineer" or "marketing specialist").
- `key_skills`: list of 2–4 skills or strengths, ideally aligned to the job description.
- `achievements`: list of short stories, each with at least:
  - `context`: where this happened (role, organisation, project).
  - `task`: what you were responsible for.
  - `action`: what you did.
  - `result`: measurable outcome (for example percentage change, volume handled, time saved).

### Motivation hooks

- `motivation_hooks`: list of 1–3 reasons you want this organisation or role, for example:
  - interest in a product or mission.
  - alignment with values or ways of working.
  - enthusiasm for a particular technology or domain.

If none are provided, the script should derive at least one generic but honest line from the role and responsibilities so that the letter never falls back to vague praise.

### Experience emphasis preference

- `experience_weight`: one of `"light"`, `"balanced"`, `"heavy"`.
  - `light`: for school leavers, graduates, career changers or people with limited directly relevant experience.
  - `balanced`: for most applicants with some experience and interest in highlighting both track record and motivation.
  - `heavy`: for experienced applicants who want the letter to focus mainly on achievements and outcomes.

### Contact details

- `email`: professional email address.
- `phone`: telephone number.
- `optional_links`: list of optional links, for example LinkedIn, portfolio or Git repository.

## Hard minimum requirements

To prevent weak output, enforce these checks before generation:

1. `job_title` and `company_name` must be present.
2. `key_responsibilities` must contain at least one item.
3. `key_skills` must contain at least one item.
4. `achievements` must contain at least one story with a non empty result.
5. `motivation_hooks` must contain at least one hook; if not, derive a generic hook during the decision phase.
6. `email` and `phone` must be present.
7. Word count after generation must be between 100 and 300.

If any of these fail, the script should raise an error instead of returning a letter.

## Harvard influenced structural rules

Harvard career guidance emphasises a conventional business structure with clear opening, middle and closing, plus specific practical tips:

- Opening paragraph: clearly state why you are writing, name the position, and briefly explain why you are interested and a good fit.
- Middle paragraph(s): connect your story to the position with specific examples, without repeating your CV line by line.
- Closing paragraph: reiterate interest, mention how to contact you, and thank the reader.
- Address a specific person if possible and use a professional salutation.
- Keep letters concise, factual and no longer than a single page.
- Avoid flowery language and overuse of the pronoun "I".
- Use action verbs and emphasise impact and achievements.
- Tailor each letter by referencing skills and experiences from the job description and drawing clear connections.

These rules are compatible with an email style, short cover letter. The script should organise content into three logical blocks that map to Harvard’s opening, middle and closing structure.

## Overall write pattern

The script should always follow the same high level pattern when rendering text:

1. Greeting
2. Opening hook and context
3. Experience and skills block (length varies with `experience_weight`)
4. Motivation and fit block
5. Call to action and closing
6. Signature and contact details

### 1. Greeting

Rules:

- Use `"Hi {name}"` when a recruiter or hiring manager name is available.
- Otherwise use `"Hi"` on its own.
- Optionally add a brief well wish (for example "I hope you are well") to set a friendly tone.

### 2. Opening hook and context

Rules:

- Clearly state that you are applying for `{job_title}` at `{company_name}`.
- Mention `application_source` if available.
- In one short sentence, summarise who you are (field or title) and one or two key skills aligned to the role.
- Avoid long formal phrases; prefer direct language (for example "I would like to apply for" rather than "I am writing to notify you that").

Example pattern:

> I would like to apply for the {job_title} role at {company_name}, which I saw on {application_source}. As a {field_or_title} with experience in {key_skill_1} and {key_skill_2}, I can help you with {responsibility_snippet}.

### 3. Experience and skills block

Rules:

- Purpose: prove fit using specific examples linked to the job description.
- Use mapped achievements that directly address the selected key responsibilities.
- Each story should include task, action and result.
- Include at least one quantified outcome.
- Do not list every job; select 1–3 of the strongest relevant stories.

Experience emphasis variants:

- `light`:
  - Include one short story.
  - Focus more on transferable skills and potential.
- `balanced`:
  - Use two stories and at least one metric.
- `heavy`:
  - Use three or more stories, each with a metric.
  - This block can become two short paragraphs in a longer letter.

Example pattern for one story:

> In my current role as {current_role} at {context_org}, I {task_phrase}, where I {action_phrase}, improving {metric_target} by {metric_value}.

### 4. Motivation and fit block

Rules:

- Explain briefly why you want this specific employer or role.
- Use a selected motivation hook and link it to your skills or experience.
- Keep this one or two sentences long.

Example pattern:

> I am particularly interested in {company_name} because {motivation_hook}. I would like to bring my {skill_or_strength} to support {company_goal_or_project}.

### 5. Call to action and closing paragraph

Rules:

- Reiterate interest and enthusiasm.
- Invite further discussion or an interview.
- Keep it concise and confident, not desperate.
- Include phone and email within this paragraph or immediately after.

Example pattern:

> I would welcome the chance to discuss how my experience can help {company_name} address {responsibility_or_goal}. You can reach me on {phone} or at {email} if you would like to arrange an interview.

### 6. Signature and contact details

Rules:

- Use a professional sign off such as "Kind regards" or "Best regards".
- Follow with full name.
- Repeat phone and email if not mentioned in the closing paragraph.
- Optionally add one or two links, for example LinkedIn.

Example pattern:

> Kind regards
>
> {candidate_name}
>
> {phone}
>
> {email}
>
> {optional_link_1}

## Decision logic in detail

To turn inputs into a letter, the script should follow this sequence.

### Step 1: Validate inputs

- Check hard minimum requirements.
- If any fail, raise a descriptive exception.

### Step 2: Rank responsibilities

- Take `key_responsibilities` and select up to three priority responsibilities.
- Simple approach: use the first three entries.
- Optional extension: score responsibilities by keywords that match user skills.

### Step 3: Map achievements to responsibilities

- For each priority responsibility, look for achievements whose task or context includes overlapping keywords.
- Build a mapping structure, for example `responsibility -> list of matching achievements`.
- If a responsibility has no direct match, plan to cover it with a transferable skill sentence instead of a full story.

### Step 4: Select achievements by experience weight

- For `light`, choose one best matching achievement, prioritising those with strong metrics.
- For `balanced`, choose two distinct achievements.
- For `heavy`, choose three or more achievements, ideally covering different responsibilities.

### Step 5: Build experience sentences

- For each selected achievement, construct a sentence using a fixed template.
- Ensure variety in sentence openings to avoid repeating "I" constantly.
- Example variations:
  - "At {context_org}, I…"
  - "In my work as {current_role}, I…"
  - "Recently, I…"

### Step 6: Select or derive motivation hook

- If `motivation_hooks` is non empty, choose the first or allow the caller to provide an index.
- If empty, derive a generic hook, for example:
  - "your focus on {responsibility_keyword}".
  - "working with {technology_or_domain}".

### Step 7: Assemble blocks

- Use the write pattern to build each block in order.
- Concatenate with line breaks between logical paragraphs.
- Keep paragraphs short (one to three sentences each).

### Step 8: Enforce length and adjust

- Count words in the generated text.
- If over 300, remove the weakest experience sentence or shorten motivation.
- If under 100, add an extra detail to experience or a second sentence to motivation.

### Step 9: Return letter text

- Return the final string.

## Sketch of Python functions and signatures

Below are suggested function names and argument lists that reflect this logic.

### Data structures

You can implement these as simple data classes or plain dictionaries.

```python
from dataclasses import dataclass
from typing import List, Optional

@dataclass
class Achievement:
    context_org: str
    role: str
    task: str
    action: str
    result: str

@dataclass
class JobData:
    job_title: str
    company_name: str
    application_source: Optional[str]
    key_responsibilities: List[str]

@dataclass
class UserProfile:
    candidate_name: str
    current_role: str
    field_or_title: str
    key_skills: List[str]
    achievements: List[Achievement]
    motivation_hooks: List[str]
    email: str
    phone: str
    optional_links: List[str]

@dataclass
class GenerationSettings:
    experience_weight: str  # "light", "balanced", or "heavy"
    recruiter_name: Optional[str] = None
```

### Validation helpers

```python
def validate_inputs(job: JobData, user: UserProfile, settings: GenerationSettings) -> None:
    """Raise ValueError if required data is missing or inconsistent."""
    ...
```

### Responsibility ranking and mapping

```python
from typing import Dict

def select_priority_responsibilities(job: JobData, max_count: int = 3) -> List[str]:
    """Return up to max_count key responsibilities in priority order."""
    ...

def map_achievements_to_responsibilities(
    responsibilities: List[str], achievements: List[Achievement]
) -> Dict[str, List[Achievement]]:
    """Map each responsibility to matching achievements based on simple keyword overlap."""
    ...
```

### Experience selection

```python
def select_experience_stories(
    mapping: Dict[str, List[Achievement]],
    experience_weight: str,
    max_total: int = 3,
) -> List[Achievement]:
    """Choose a list of achievements to feature, based on experience weight."""
    ...
```

### Sentence rendering

```python
def render_greeting(settings: GenerationSettings) -> str:
    """Return the greeting line."""
    ...

def render_opening(job: JobData, user: UserProfile) -> str:
    """Return the opening hook and context paragraph."""
    ...

def render_experience_block(
    stories: List[Achievement], job: JobData, user: UserProfile, experience_weight: str
) -> str:
    """Return one or two short paragraphs that describe experience and skills."""
    ...

def select_motivation_hook(user: UserProfile, job: JobData) -> str:
    """Pick or derive a motivation hook string."""
    ...

def render_motivation_block(hook: str, job: JobData, user: UserProfile) -> str:
    """Return one short paragraph about motivation and fit."""
    ...

def render_closing(job: JobData, user: UserProfile) -> str:
    """Return closing paragraph including call to action and contact info."""
    ...

def render_signature(user: UserProfile) -> str:
    """Return signature and contact block."""
    ...
```

### Assembly and length control

```python
def assemble_cover_letter(
    greeting: str,
    opening: str,
    experience_block: str,
    motivation_block: str,
    closing: str,
    signature: str,
) -> str:
    """Join all blocks into a full cover letter string."""
    ...

def enforce_length(letter_text: str, experience_block: str, motivation_block: str) -> str:
    """Adjust or trim blocks to keep letter within target word count."""
    ...
```

### Main generation function

```python
def generate_cover_letter(job: JobData, user: UserProfile, settings: GenerationSettings) -> str:
    """High level function that orchestrates validation, decisions and rendering."""
    validate_inputs(job, user, settings)
    responsibilities = select_priority_responsibilities(job)
    mapping = map_achievements_to_responsibilities(responsibilities, user.achievements)
    stories = select_experience_stories(mapping, settings.experience_weight)

    greeting = render_greeting(settings)
    opening = render_opening(job, user)
    experience_block = render_experience_block(stories, job, user, settings.experience_weight)
    hook = select_motivation_hook(user, job)
    motivation_block = render_motivation_block(hook, job, user)
    closing = render_closing(job, user)
    signature = render_signature(user)

    letter = assemble_cover_letter(
        greeting,
        opening,
        experience_block,
        motivation_block,
        closing,
        signature,
    )
    letter = enforce_length(letter, experience_block, motivation_block)
    return letter
```

This md file can serve as the specification when you build your `.py` module. You can start by defining the data classes and stub functions with `pass`, then implement each piece following the rules above.