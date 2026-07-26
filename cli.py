import asyncio
import argparse
import sys
from loguru import logger
from pathlib import Path

from src.video_agent.core.agent import VideoAgent

def setup_logging():
    logger.remove()
    logger.add(sys.stdout, format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan> - <level>{message}</level>", level="INFO")

async def async_main():
    parser = argparse.ArgumentParser(description="Video Agent CLI")
    parser.add_argument("goal", type=str, help="The natural language goal for the video")
    parser.add_argument("--workspace", type=str, default="./workspace", help="Directory for state persistence")
    parser.add_argument("--workflow", type=str, default="./config/default_workflow.json", help="Path to workflow definition")
    
    args = parser.parse_args()
    
    setup_logging()
    
    agent = VideoAgent(workspace_dir=args.workspace)
    await agent.run(user_goal=args.goal, workflow_config_path=args.workflow)

def main():
    asyncio.run(async_main())

if __name__ == "__main__":
    main()
