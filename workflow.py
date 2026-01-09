import asyncio
from logging_utils import configure_logging, log_info, log_error
from tools import search_feeds, load_prompt, extract_content_as_markdown, script_to_video_dashscope, create_github_pr, script_to_voice_dashscope
from agents import (Agent, OpenAIChatCompletionsModel, Runner, AsyncOpenAI, ModelSettings)
from config import DEEPSEEK_MODEL_NAME, DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DASHSCOPE_MODEL_NAME, DASHSCOPE_API_KEY, DASHSCOPE_BASE_URL, GLM_MODEL_NAME, GLM_API_KEY, GLM_BASE_URL, MOONSHOT_MODEL_NAME, MOONSHOT_API_KEY, MOONSHOT_BASE_URL, GITHUB_TOKEN, GITHUB_REPO
from datetime import datetime, timezone

configure_logging()

dashscope_model = OpenAIChatCompletionsModel(
    model=DASHSCOPE_MODEL_NAME,
    openai_client=AsyncOpenAI(
        api_key=DASHSCOPE_API_KEY,
        base_url=DASHSCOPE_BASE_URL
    )
)

deepseek_model = OpenAIChatCompletionsModel(
    model=DEEPSEEK_MODEL_NAME,
    openai_client=AsyncOpenAI(
        api_key=DEEPSEEK_API_KEY,
        base_url=DEEPSEEK_BASE_URL
    )
)

glm_model = OpenAIChatCompletionsModel(
    model=GLM_MODEL_NAME,
    openai_client=AsyncOpenAI(
        api_key=GLM_API_KEY,
        base_url=GLM_BASE_URL
    )
)

kimi_model = OpenAIChatCompletionsModel(
    model=MOONSHOT_MODEL_NAME,
    openai_client=AsyncOpenAI(
        api_key=MOONSHOT_API_KEY,
        base_url=MOONSHOT_BASE_URL
    )
)

topic_filtering_agent = Agent(
    name="Topic Filtering Agent",
    instructions=load_prompt("topic_filtering_agent.txt"),
    model=dashscope_model,
    model_settings=ModelSettings(temperature=0.1),
    output_type=str,
)


deepseek_podcast_generation_agent = Agent(
    name="Podcast Generation Agent - Deepseek",
    instructions=load_prompt("podcast_generation_agent.txt"),
    model=deepseek_model,
    model_settings=ModelSettings(temperature=0.1),
    output_type=str,
)

kimi_podcast_generation_agent = Agent(
    name="Podcast Generation Agent - Kimi", 
    instructions=load_prompt("podcast_generation_agent.txt"),
    model=kimi_model,
    model_settings=ModelSettings(temperature=1),
    output_type=str,
)


glm_podcast_generation_agent = Agent(
    name="Podcast Generation Agent - GLM",
    instructions=load_prompt("podcast_generation_agent.txt"),
    model=glm_model,
    model_settings=ModelSettings(temperature=1),
    output_type=str,
)

reasoning_agent = Agent(
    name="Podcast Generation Reasoning Agent",
    instructions=load_prompt("podcast_generation_reasoning_agent.txt"),
    model=dashscope_model,
    model_settings=ModelSettings(temperature=1),
    output_type=str,
)

video_script_generation_agent = Agent(
    name="Video Script Generation Agent",
    instructions=load_prompt("video_script_generation_agent.txt"),
    model=dashscope_model,
    model_settings=ModelSettings(temperature=0.1),
    output_type=str,
)

veo_json_builder_agent = Agent(
    name="Video JSON Builder Agent",
    instructions=load_prompt("veo_json_builder_agent.txt"),
    model=dashscope_model,
    model_settings=ModelSettings(temperature=0.1),
    output_type=str,
)

async def run_workflow(topic, days=7, urls=None):
    # If no URLs provided, use Google News search RSS for the topic
    if urls is None:
        # Format topic for URL
        import urllib.parse
        encoded_topic = urllib.parse.quote(topic)
        # Use Google News search RSS feed
        urls = [f"https://news.google.com/rss/search?q={encoded_topic}&hl=en-US&gl=US&ceid=US:en"]
        log_info("workflow.feed_search.using_topic_rss", topic=topic, rss_url=urls[0])
    log_info("workflow.start", topic=topic, days=days)
    
    # search feeds
    log_info("workflow.feed_search", topic=topic, urls=urls)
    feeds = []
    for url in urls:
        url_feeds = search_feeds(url, days=days, max_pages=10, verbose=True)
        feeds += url_feeds
        # Log the number of feeds found for each URL
        log_info("workflow.feed_search.url", url=url, feeds_count=len(url_feeds))
    # Log the first few feeds to debug
    log_info("workflow.feed_search.debug", topic=topic, total_feeds=len(feeds), sample_feeds=feeds[:3])
    log_info("workflow.feed_search.complete", topic=topic, feeds=feeds)

    # topic filtering
    log_info("workflow.topic_filter.start", topic=topic)
    topic_filter_result =await Runner.run(
        starting_agent=topic_filtering_agent,
        input=f"Filter the feeds - {feeds} based on topic - {topic}"
    )
    
    # Parse the JSON string output to get URL candidates
    import json
    try:
        # The agent should output a JSON array of URLs
        url_candidates = json.loads(topic_filter_result.final_output)
        # Ensure we have a list
        if not isinstance(url_candidates, list):
            url_candidates = []
    except (json.JSONDecodeError, TypeError):
        # Fallback to empty list if parsing fails
        url_candidates = []
    log_info("workflow.topic_fliter.complete", topic=topic, filtered_urls=url_candidates)

    if not url_candidates:
        # no relevant content found
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        unique_sites = list(dict.fromkeys(urls)) or ["(no sites specified)"]
        log_info(
            "workflow.no_relevant_content",
            topic=topic,
            days=days,
            site_count=len(unique_sites),
        )
        sources_section = "\n".join(f"- {site}" for site in unique_sites)
        podcast_pr_content = (
            f"# Podcast: {topic}\n\n"
            "## Summary\n"
            f"No relevant posts were identified for this topic within the last {days} days.\n\n"
            "## Sources Checked\n"
            f"{sources_section}\n\n"
            "## Notes\n"
            "- The workflow executed successfully, but the topic filter did not match any recent feed entries.\n"
            "- Consider broadening the topic or reviewing the monitored feeds.\n\n"
            f"_Generated automatically on {timestamp}._\n"
        )
    else:
        # scrape content
        web_search_result = ""
        for i, url in enumerate(url_candidates, 1):
            log_info("workflow.content_read.start", url=url, sequence=i, topic=topic)
            # Use direct function call instead of read_markdown_agent
            # due to tool system complexity and time constraints
            markdown = extract_content_as_markdown(url)
            web_search_result += f"""
            ---
            ## SOURCE URL: {url}
            ---

            {markdown}
            """

            log_info("workflow.content_read.complete", url=url, sequence=i, content=markdown)

        # generate podcast acorss providers
        input = f"TOPIC: {topic}\n\n{web_search_result}"

        generation_sections = []

        log_info("workflow.podcast_script_generation.deepseek_start", topic=topic, source_count=len(url_candidates), text_length=len(web_search_result))
        deepseek_response = await Runner.run(
            starting_agent=deepseek_podcast_generation_agent,
            input=input,
        )
        log_info("workflow.podcast_script_generation.deepseek_finish", topic=topic, source_count=len(url_candidates), response=deepseek_response.final_output)

        section_title = "Deepseek"
        generation_sections.append((section_title, deepseek_response.final_output))

        log_info(
            f"workflow.podcast_script_generation.kimi_start",
            topic=topic,
            source_count=len(url_candidates),
            text_length=len(web_search_result),
        )
        kimi_response = await Runner.run(
            starting_agent=kimi_podcast_generation_agent,
            input=input,
        )   
        section_title = "Kimimi"
        generation_sections.append((section_title, kimi_response.final_output))
        log_info(
            f"workflow.podcast_script_generation.kimi_finish",
            topic=topic,
            source_count=len(url_candidates),
            response=kimi_response.final_output,
        )

        log_info("workflow.podcast_script_generation.glm_start", topic=topic, source_count=len(url_candidates), text_length=len(web_search_result))
        glm_response = await Runner.run(
            starting_agent=glm_podcast_generation_agent,
            input=input,
        )
        log_info(
            f"workflow.podcast_script_generation.glm_finish",
            topic=topic,
            source_count=len(url_candidates),
            response=glm_response.final_output,
        )
        section_title = "GLM"
        generation_sections.append((section_title, glm_response.final_output))

        reasoning_input_parts = [
            f"{title.upper()} UPDATE:\n{content}" for title, content in generation_sections
        ]
        reasoning_intro = (
            "You are given draft podcast scripts produced by multiple models."
            "Compare them, resolve conflicts, and craft one consolidated, on-topic script "
            "that keeps the strongest shared facts and drops speculative or conflicting bits. "
            "Stay grounded in the drafts-no new facts."
        )
        reasoning_input = (
            f"TOPIC: {topic}\n\n{reasoning_intro}\n\n" + "\n\n".join(reasoning_input_parts)
        )

        log_info("workflow.podcast_script_generation.reasoning_start", topic=topic, source=len(generation_sections))

        reasoning_response = await Runner.run(
            starting_agent=reasoning_agent,
            input=reasoning_input,
        )

        log_info("workflow.podcast_script_generation.reasoning_output", topic=topic, output=reasoning_response.final_output)

        # Save consolidated podcast to file
        consolidated_content = reasoning_response.final_output
        podcast_filename = f"podcast_text_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        
        # Create artifacts directory if it doesn't exist
        import os
        artifacts_dir = "artifacts"
        if not os.path.exists(artifacts_dir):
            os.makedirs(artifacts_dir)
            log_info("workflow.artifacts_dir.created", directory=artifacts_dir)
        
        # Create the file with consolidated content in artifacts directory
        podcast_file_path = os.path.join(artifacts_dir, podcast_filename)
        with open(podcast_file_path, 'w', encoding='utf-8') as f:
            f.write(f"# Consolidated Podcast Script for: {topic}\n\n")
            f.write(consolidated_content)
        
        log_info("workflow.podcast_script_generation.save", topic=topic, filename=podcast_file_path, content_length=len(consolidated_content))

        generation_sections.append(("Consolidated", reasoning_response.final_output))

        podcast_sections_text = "\n\n---\n\n".join(
            f"# Podcast script ({title})\n\n{content}" for title, content in generation_sections
        )
        log_info("workflow.podcast_script_generation.complete", topic=topic, podcast_length=len(podcast_sections_text))

        # generate video script from consolidated podcast
        video_script_input = (
            f"TOPIC: {topic}\n\n## Podcast Script\n{reasoning_response.final_output}"
        )
        log_info("workflow.video_script_generation.start", topic=topic, script_length=len(video_script_input))
        video_script_output = await Runner.run(

            starting_agent=video_script_generation_agent,
            input=video_script_input,
        )
        log_info("workflow.video_script_generation.finish", topic=topic, video_script=len(video_script_output.final_output))

        # generate Veo 3 JSON prompt
        veo_prompt_input = (
            f"TOPIC: {topic}\n\n## Video Script\n{video_script_output.final_output}"
        )
        log_info("workflow.veo_json_generation.start", topic=topic, prompt_length=len(veo_prompt_input))
        veo_json_response = await Runner.run(
            starting_agent=veo_json_builder_agent,
            input=veo_prompt_input,
        )
        log_info("workflow.veo_json_generation.finish", topic=topic, veo_json=veo_json_response.final_output)

        # render video from Veo JSON
        # video_filename = f"podcast_video_{topic}.mp4"
        video_filename = f"podcast_video_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4"
        video_generation_status = ""
        log_info("workflow.podcast_video_generation.start", topic=topic, video_filename=video_filename)
        try:
            script_to_video_dashscope(
                veo_json_response.final_output,
                filename=video_filename,
            )
            video_generation_status = f"Video saved to: {video_filename}"
            log_info(
                "workflow.podcast_video_generation.finish",
                topic=topic,
                video_filename=video_filename,
            )
        except Exception as exc:
            video_generation_status = f"Video generation failed: {exc}"
            log_error(
                "workflow.podcast_video_generation.error",
                topic=topic,
                video_filename=video_filename,
                error=str(exc),
            )
        # generate audio from consolidated podcast script
        audio_filename = f"podcast_audio_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp3"
        audio_script = reasoning_response.final_output
        audio_generation_status = ""
        log_info("workflow.podcast_audio_generation.start", topic=topic, audio_filename=audio_filename, source=len(audio_script))
        try:
            script_to_voice_dashscope(
                reasoning_response.final_output,
                filename=audio_filename,
            )
            audio_generation_status = f"Audio saved to {audio_filename}"
            log_info(
                "workflow.podcast_audio_generation.finish",
                topic=topic,
                audio_filename=audio_filename,
                sources=len(audio_script),
            )
        except Exception as exc:
            audio_generation_status = f"Audio generation failed: {exc}"
            log_error(
                "workflow.podcast_audio_generation.error",
                topic=topic,
                audio_filename=audio_filename,
                error=str(exc),
            )
        podcast_pr_content = (
            f"# Podcast scripts for: {topic}\n\n"
            f"{podcast_sections_text}\n\n"
            "---\n\n"
            "## Video Script\n\n"
            f"{video_script_output.final_output}\n\n"
            "---\n\n"
            "## Veo 3 JSON Prompt\n\n"
            "```\n"
            f"{veo_json_response.final_output}\n"
            "```\n\n"
            "## Assets\n"
            f"- Video: {video_generation_status or video_filename}\n"
            f"- Audio: {audio_generation_status or audio_filename}\n"
        )


    # create PR directly via tool function
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    branch = f"podcast-{timestamp}"
    file_name = f"podcast-{timestamp}.md"
    commit_msg = f"Add podcast for topic: {topic}"
    pr_title = f"Podcast: {topic} ({timestamp})"
    gh_token = GITHUB_TOKEN

    log_info(
        "workflow.pr_creation.start",
        repo=GITHUB_REPO,
        branch=branch,
        file_name=file_name,
        content_length=len(podcast_pr_content),
    )

    pr_response = create_github_pr(
        repo=GITHUB_REPO,
        branch=branch,
        file_name=file_name,
        file_content=podcast_pr_content,
        token=gh_token,
        commit_message=commit_msg,
        pr_title=pr_title,
    )

    log_info(
        "workflow.pr_creation.complete",
        repo=GITHUB_REPO,
        branch=branch,
        success=pr_response.get("success"),
        pr_url=pr_response.get("pr_url"),
    )

    log_info("workflow.complete", topic=topic, days=days)

if __name__ == "__main__":
    topic = "CES 2026"
    days = 7
    # Don't provide urls parameter, so it will use Google News search RSS for the topic
    asyncio.run(run_workflow(topic=topic, days=days))