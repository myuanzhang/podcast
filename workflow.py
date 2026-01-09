import asyncio
from logging_utils import configure_logging, log_info, log_error
from tools import search_feeds, load_prompt, extract_content_as_markdown, script_to_video_dashscope, create_github_pr, script_to_voice_dashscope
from agents import (Agent, OpenAIChatCompletionsModel, Runner, AsyncOpenAI, ModelSettings)
from config import GEMINI_MODEL_NAME, GEMINI_API_KEY, GEMINI_BASE_URL, DEEPSEEK_MODEL_NAME, DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DASHSCOPE_MODEL_NAME, DASHSCOPE_API_KEY, DASHSCOPE_BASE_URL, GLM_MODEL_NAME, GLM_API_KEY, GLM_BASE_URL, GITHUB_TOKEN, GITHUB_REPO
from typing import List
from datetime import datetime

configure_logging()

dashscope_model = OpenAIChatCompletionsModel(
    model=DASHSCOPE_MODEL_NAME,
    openai_client=AsyncOpenAI(
        api_key=DASHSCOPE_API_KEY,
        base_url=DASHSCOPE_BASE_URL
    )
)

gemini_model = OpenAIChatCompletionsModel(
    model=GEMINI_MODEL_NAME,
    openai_client=AsyncOpenAI(
        api_key=GEMINI_API_KEY,
        base_url=GEMINI_BASE_URL
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

topic_filtering_agent = Agent(
    name="Topic Filtering Agent",
    instructions=load_prompt("topic_filtering_agent.txt"),
    model=dashscope_model,
    model_settings=ModelSettings(temperature=0.1),
    output_type=List[str],
)

read_markdown_agent = Agent(
    name="Read Web Page Markdown Agent",
    tools=[extract_content_as_markdown],
    instructions=load_prompt("read_markdown_agent.txt"),
    model=dashscope_model,
    model_settings=ModelSettings(temperature=1),
    output_type=str,
)

gemini_podcast_generation_agent = Agent(
    name="Podcast Generation Agent - Gemini",
    instructions=load_prompt("podcast_generation_agent.txt"),
    model=gemini_model,
    model_settings=ModelSettings(temperature=0.1),
    output_type=str,
)

dashscope_podcast_generation_agent = Agent(
    name="Podcast Generation Agent - DashScope",
    instructions=load_prompt("podcast_generation_agent.txt"),
    model=dashscope_model,
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
    model=deepseek_model,
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

async def run_workflow(topic, days=7, urls=["https://www.cbsnews.com/"]):
    log_info("workflow.start", topic=topic, days=days)
    
    # search feeds
    log_info("workflow.feed_search", topic=topic, urls=urls)
    feeds = []
    for url in urls:
        feeds += search_feeds(url, days=days, max_pages=10, verbose=True)
    log_info("workflow.feed_search.complete", topic=topic, feeds=feeds)

    # topic filtering
    log_info("workflow.topic_filter.start", topic=topic)
    topic_filter_result =await Runner.run(
        starting_agent=topic_filtering_agent,
        input=f"Filter the feeds - {feeds} based on topic - {topic}"
    )
    topics = topic_filter_result.final_output
    url_candidates = topics or []
    log_info("workflow.topic_fliter.complete", topic=topic, filtered_urls=url_candidates)

    if not url_candidates:
        # no relevant content found
        timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
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

        log_info("workflow.podcast_script_generation.gemini_start", topic=topic, source_count=len(url_candidates), text_length=len(web_search_result))

        gemini_response = await Runner.run(
            starting_agent=gemini_podcast_generation_agent,
            input=input,
        )
        log_info("workflow.podcast_script_generation.gemini_finish", topic=topic, source_count=len(url_candidates), response=gemini_response.final_output)

        section_title = "Gemini"
        generation_sections.append((section_title, gemini_response.final_output))

        log_info(
            f"workflow.podcast_script_generation.dashscope_start",
            topic=topic,
            source_count=len(url_candidates),
            text_length=len(web_search_result),
        )
        dashscope_response = await Runner.run(
            starting_agent=dashscope_podcast_generation_agent,
            input=input,
        )   
        section_title = "DashScope"
        generation_sections.append((section_title, dashscope_response.final_output))
        log_info(
            f"workflow.podcast_script_generation.dashscope_finish",
            topic=topic,
            source_count=len(url_candidates),
            response=dashscope_response.final_output,
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
    topic = "Meta收购Manus"
    days = 7
    urls = ["https://news.qq.com/"]
    asyncio.run(run_workflow(topic=topic, days=days, urls=urls))