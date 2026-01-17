# WordPress Article Generator

A Python-based automated article generation system that uses OpenAI's API to create content and publishes it to WordPress via the REST API. Designed for high-volume content production (1000+ articles) with built-in rate limiting, checkpoint/resume functionality, and concurrent processing.

## Features

- **AI-Powered Content Generation**: Uses OpenAI GPT models to generate high-quality articles
- **WordPress REST API Integration**: Publish directly to WordPress with draft/publish control
- **Concurrent Processing**: Generate and publish multiple articles simultaneously
- **Rate Limiting**: Built-in throttling to protect your WordPress server and API quotas
- **Checkpoint/Resume**: State persistence allows resuming interrupted sessions
- **Progress Tracking**: Real-time progress monitoring with detailed statistics
- **Configurable Prompts**: Customizable AI prompts for different tones and styles
- **SEO Support**: Automatic title and excerpt generation

## Project Structure

```
wenzhang/
├── config/
│   ├── config.yaml              # Main configuration (create from example)
│   ├── config.example.yaml      # Configuration template
│   └── prompts.yaml             # AI prompt templates
├── src/
│   ├── wordpress_client.py      # WordPress REST API client
│   ├── ai_generator.py          # OpenAI integration
│   ├── article_generator.py     # Main orchestrator
│   ├── batch_processor.py       # Concurrent processing
│   ├── rate_limiter.py          # Rate limiting
│   ├── state_manager.py         # State persistence
│   ├── progress_tracker.py      # Progress monitoring
│   └── utils/
│       ├── logger.py            # Logging configuration
│       └── retry_handler.py     # Retry logic
├── data/
│   ├── state/                   # Runtime state files
│   ├── keywords.csv             # Your topics list
│   └── templates/               # Article templates
├── logs/
│   └── generator.log
├── scripts/
│   ├── run.py                   # Main execution script
│   └── resume.py                # Resume interrupted sessions
├── requirements.txt
├── .env.example
└── README.md
```

## Installation

### Prerequisites

- Python 3.8+
- WordPress site with REST API enabled
- OpenAI API key
- WordPress Application Password

### Setup

1. **Clone or navigate to the project directory:**
   ```bash
   cd /Users/guobinli/xm/wenzhang
   ```

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Create configuration file:**
   ```bash
   cp config/config.yaml config/config.local.yaml
   # Edit config.local.yaml with your settings
   ```

4. **Set up environment variables (optional):**
   ```bash
   cp .env.example .env
   # Edit .env with your credentials
   ```

## Configuration

### WordPress Setup

1. **Generate an Application Password:**
   - Go to WordPress Admin > Users > Profile
   - Scroll to "Application Passwords"
   - Enter a name (e.g., "Article Generator")
   - Copy the generated password

2. **Update configuration:**
   ```yaml
   wordpress:
     base_url: "https://your-site.com/wp-json"
     credentials:
       username: "your_username"
       application_password: "your_application_password"
   ```

### OpenAI Setup

1. **Get an API key** from [platform.openai.com](https://platform.openai.com/api-keys)

2. **Update configuration:**
   ```yaml
   openai:
     api_key: "sk-your-api-key-here"
     model: "gpt-4o"  # or gpt-4-turbo-preview, gpt-3.5-turbo
   ```

### Prepare Topics

Create a file `data/keywords.csv` with one topic per line:
```csv
Introduction to Machine Learning
Web Development Best Practices
Cloud Computing Trends 2026
```

Or specify topics in `config.yaml`:
```yaml
topics:
  - "Introduction to Machine Learning"
  - "Web Development Best Practices"
```

## Usage

### Basic Generation

```bash
python scripts/run.py
```

### Specify Topics

```bash
python scripts/run.py --topic "AI in Healthcare" --topic "Blockchain Basics"
```

### Use Topics File

```bash
python scripts/run.py --topics-file data/keywords.csv
```

### Test Connection

```bash
python scripts/run.py --test-connection
```

### Test Mode (Single Article)

```bash
python scripts/run.py --test-mode --topic "Test Topic"
```

### Resume Interrupted Session

```bash
# List available sessions
python scripts/run.py --list-sessions

# Resume specific session
python scripts/run.py --resume --session-id 20240115_143022
```

### Retry Failed Articles

```bash
python scripts/run.py --retry-failed --session-id 20240115_143022
```

### Change Writing Tone

```bash
python scripts/run.py --tone casual
```

Available tones: `professional`, `casual`, `friendly`, `technical`, `marketing`

## Advanced Usage

### Custom Configuration

```bash
python scripts/run.py --config /path/to/custom-config.yaml
```

### Programmatic Usage

```python
import asyncio
from src.article_generator import generate_articles

async def main():
    result = await generate_articles(
        config_path="config/config.yaml",
        topics=["Topic 1", "Topic 2"],
        tone="professional"
    )
    print(f"Generated {result['successful']} articles")

asyncio.run(main())
```

### Using as a Library

```python
from src.article_generator import ArticleGenerator

async def generate():
    generator = ArticleGenerator("config/config.yaml")
    await generator.initialize(
        session_id="my_session",
        topics=["Topic 1", "Topic 2"]
    )
    result = await generator.generate(tone="professional")
    return result
```

## State Management

The generator automatically saves progress every 10 articles (configurable). If interrupted:

1. **List available sessions:**
   ```bash
   python scripts/run.py --list-sessions
   ```

2. **Resume a session:**
   ```bash
   python scripts/run.py --resume --session-id <session_id>
   ```

Or use the dedicated resume script:
```bash
python scripts/resume.py --list
python scripts/resume.py --session-id <session_id>
```

## Configuration Options

| Setting | Description | Default |
|---------|-------------|---------|
| `wordpress.rate_limit.requests_per_minute` | API request rate limit | 60 |
| `generation.max_concurrent` | Concurrent article generation | 5 |
| `generation.checkpoint_interval` | State save frequency (articles) | 10 |
| `openai.model` | OpenAI model to use | gpt-4o |
| `openai.temperature` | Content creativity (0-2) | 0.7 |
| `content.default_status` | WordPress post status | draft |

## Cost Estimation

For 1000 articles:

| Model | Cost per article | Total cost |
|-------|------------------|------------|
| GPT-4o | ~$0.05 | ~$50 |
| GPT-4-turbo-preview | ~$0.03 | ~$30 |
| GPT-3.5-turbo | ~$0.002 | ~$2 |

*Costs vary based on article length and actual token usage.*

## Troubleshooting

### Connection Issues

```bash
# Test WordPress connection
python scripts/run.py --test-connection
```

### Rate Limiting

If you hit rate limits:
- Reduce `max_concurrent` in config
- Increase `requests_per_minute` limit
- Use a longer delay between batches

### Authentication Failures

1. Verify Application Password is correct
2. Check WordPress username
3. Ensure REST API is enabled on your WordPress site
4. Confirm SSL certificate is valid (or set `verify_ssl: false`)

## License

MIT

## Contributing

Contributions welcome! Please feel free to submit pull requests.

## Disclaimer

This tool is for educational and legitimate content creation purposes only. Users are responsible for:
- Complying with OpenAI's terms of service
- Following WordPress best practices
- Ensuring generated content meets their quality standards
- Reviewing content before publishing
