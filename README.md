# TSSPDCL Voice Agent

A voice-enabled customer care system for TSSPDCL (Telangana State Southern Power Distribution Company Limited) that handles complaint registration and status checking through voice interactions.

## Features

- 🎤 **Voice Interface**: Powered by Deepgram for speech-to-text and text-to-speech
- 📞 **Twilio Integration**: Handles phone calls via WebSocket
- 🤖 **AI Agent**: OpenAI GPT-4 for intelligent conversation handling
- 🗃️ **Database Integration**: Azure SQL Database for complaint management
- 📋 **Complaint Management**: Register new complaints and check existing status
- 🔄 **Real-time Processing**: Async operations for smooth user experience

## Prerequisites

- Python 3.8+
- Deepgram API Key
- OpenAI API Key (configured through Deepgram Agent API)
- Azure SQL Database
- Twilio Account (for phone integration)
- ngrok (for local development)

## Setup Instructions

### 1. Clone the Repository
```bash
git clone https://github.com/godoffate/TSSPDCL-VOICE-AGENT.git
cd TSSPDCL-VOICE-AGENT
```

### 2. Install Dependencies
```bash
pip install -r requirements.txt
# or if using uv:
uv sync
```

### 3. Environment Configuration
```bash
cp example.env .env
```

Edit the `.env` file with your actual credentials:
```bash
# Deepgram API Key
DEEPGRAM_API_KEY="your_deepgram_api_key_here"

# Azure SQL Database
SQL_SERVER=your-server.database.windows.net
SQL_DATABASE=your_database_name
SQL_USER=your_username
SQL_PASSWORD=your_password
ODBC_DRIVER=ODBC Driver 18 for SQL Server
```

### 4. Database Setup

Create a table in your Azure SQL Database:
```sql
CREATE TABLE complaints (
    complaint_no INT IDENTITY(1,1) PRIMARY KEY,
    id NVARCHAR(36) UNIQUE NOT NULL,
    service_no NVARCHAR(50),
    name NVARCHAR(100) NOT NULL,
    area_description NVARCHAR(255),
    landmark NVARCHAR(255),
    problem_details NVARCHAR(MAX) NOT NULL,
    status NVARCHAR(50) DEFAULT 'patrolling',
    estimation_time NVARCHAR(100),
    created_time DATETIME2 NOT NULL,
    resolved_time DATETIME2,
    resolution_duration NVARCHAR(50)
);
```

### 5. Run the Application
```bash
python main.py
```

### 6. Expose Local Server (for Twilio)
In another terminal:
```bash
ngrok http 5000 --region=ap
```

## Configuration

The `config.json` file contains the agent configuration including:
- Audio settings (mulaw encoding for Twilio)
- Deepgram Nova-3 for speech recognition
- OpenAI GPT-4 for conversation handling
- Custom prompts for TSSPDCL customer care scenarios
- Function definitions for database operations

## Usage

The voice agent supports two main flows:

### 1. New Complaint Registration
- Collects customer name (mandatory)
- Asks for service number (optional)
- Gathers area description and landmark
- Records detailed problem description
- Confirms information before submission
- Provides complaint number and ID

### 2. Complaint Status Check
- Asks for customer name
- Requests complaint number or ID
- Retrieves and reads back complaint details
- Includes status, creation date, and estimated resolution time

## Architecture

```
[Phone Call] → [Twilio] → [WebSocket] → [Voice Agent] → [Deepgram Agent API] → [Database]
                                           ↓
                                    [OpenAI GPT-4]
```

## File Structure

- `main.py` - Main WebSocket server handling Twilio-Deepgram communication
- `tssdcl_sql.py` - Database operations and async function wrappers
- `config.json` - Agent configuration and prompts
- `.env` - Environment variables (not committed to git)
- `example.env` - Template for environment variables

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly
5. Submit a pull request

## License

This project is licensed under the MIT License.

## Support

For issues and questions, please open an issue on GitHub or contact the development team.
