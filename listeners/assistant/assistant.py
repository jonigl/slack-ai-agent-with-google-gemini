import logging
from random import random
from typing import List, Dict
from slack_bolt import Assistant, BoltContext, Say, SetSuggestedPrompts, SetStatus
from slack_bolt.context.get_thread_context import GetThreadContext
from slack_sdk.models.blocks import Block, ContextActionsBlock, FeedbackButtonsElement, FeedbackButtonObject
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from ai.llm_caller import call_llm

from ..views.feedback_block import create_feedback_block

# Refer to https://tools.slack.dev/bolt-python/concepts/assistant/ for more details
assistant = Assistant()

# funny thinking messages
thinking_messages = [
    "Hmm... Let me think about it.",
    "Just a moment while I process this...",
    "I'm on it! Give me a second...",
    "Let me gather my thoughts...",
    "Thinking... Please hold on.",
]

# This listener is invoked when a human user opened an assistant thread
@assistant.thread_started
def start_assistant_thread(
    say: Say,
    get_thread_context: GetThreadContext,
    set_suggested_prompts: SetSuggestedPrompts,
    logger: logging.Logger,
):
    try:
        say("How can I help you?")

        prompts: List[Dict[str, str]] = [
            {
                "title": "What does Slack stand for?",
                "message": "Slack, a business communication service, was named after an acronym. Can you guess what it stands for?",
            },
            {
                "title": "Write a draft announcement",
                "message": "Can you write a draft announcement about a new feature my team just released? It must include how impactful it is.",
            },
            {
                "title": "Suggest names for my Slack app",
                "message": "Can you suggest a few names for my Slack app? The app helps my teammates better organize information and plan priorities and action items.",
            },
        ]

        thread_context = get_thread_context()
        if thread_context is not None and thread_context.channel_id is not None:
            summarize_channel = {
                "title": "Summarize the referred channel",
                "message": "Can you generate a brief summary of the referred channel?",
            }
            prompts.append(summarize_channel)

        set_suggested_prompts(prompts=prompts)
    except Exception as e:
        logger.exception(f"Failed to handle an assistant_thread_started event: {e}", e)
        say(f":warning: Something went wrong! ({e})")


# This listener is invoked when the human user sends a reply in the assistant thread
@assistant.user_message
def respond_in_assistant_thread(
    payload: dict,
    logger: logging.Logger,
    context: BoltContext,
    set_status: SetStatus,
    get_thread_context: GetThreadContext,
    client: WebClient,
    say: Say,

):
    try:
        channel_id = payload["channel"]
        thread_ts = payload["thread_ts"]
        user_id = payload["user"]
        team_id = context.team_id
        user_message = payload["text"]
        # set a random thinking message every time we start processing a user message
        set_status(thinking_messages[int(random() * len(thinking_messages))])

        if user_message == "Can you generate a brief summary of the referred channel?":
            # the logic here requires the additional bot scopes:
            # channels:join, channels:history, groups:history
            thread_context = get_thread_context()
            referred_channel_id = thread_context.get("channel_id")
            try:
                channel_history = client.conversations_history(channel=referred_channel_id, limit=50)
            except SlackApiError as e:
                if e.response["error"] == "not_in_channel":
                    # If this app's bot user is not in the public channel,
                    # we'll try joining the channel and then calling the same API again
                    client.conversations_join(channel=referred_channel_id)
                    channel_history = client.conversations_history(channel=referred_channel_id, limit=50)
                else:
                    raise e

            prompt = f"Can you generate a brief summary of these messages in a Slack channel <#{referred_channel_id}>?\n\n"
            for message in reversed(channel_history.get("messages")):
                if message.get("user") is not None:
                    prompt += f"\n<@{message['user']}> says: {message['text']}\n"

            messages_in_thread = [{"role": "user", "content": prompt}]

            returned_message = call_llm(messages_in_thread)

            # Initialize a message streamer to stream the response
            streamer = client.chat_stream(
                channel=channel_id,
                recipient_team_id=team_id,
                recipient_user_id=user_id,
                thread_ts=thread_ts,
            )

            # Loop over OpenAI response stream
            for chunk in returned_message:
                if chunk.choices[0].delta.content is not None:
                    streamer.append(markdown_text=chunk.choices[0].delta.content)

            feedback_block = create_feedback_block()
            streamer.stop(blocks=feedback_block)
            # say(returned_message) just for reference, we now use streamer above to stream the response
            return

        replies = client.conversations_replies(
            channel=context.channel_id,
            ts=context.thread_ts,
            oldest=context.thread_ts,
            limit=10,
        )
        messages_in_thread: List[Dict[str, str]] = []
        for message in replies["messages"]:
            role = "user" if message.get("bot_id") is None else "assistant"
            messages_in_thread.append({"role": role, "content": message["text"]})

        returned_message = call_llm(messages_in_thread)
        # Initialize a message streamer to stream the response
        streamer = client.chat_stream(
            channel=channel_id,
            recipient_team_id=team_id,
            recipient_user_id=user_id,
            thread_ts=thread_ts,
        )

        # Loop over OpenAI response stream
        for chunk in returned_message:
            if chunk.choices[0].delta.content is not None:
                streamer.append(markdown_text=chunk.choices[0].delta.content)

        feedback_block = create_feedback_block()
        streamer.stop(blocks=feedback_block)

    except Exception as e:
        logger.exception(f"Failed to handle a user message event: {e}")
        say(f":warning: Something went wrong! ({e})")


@assistant.thread_context_changed
def handle_thread_context_change(
    payload: dict,
    logger: logging.Logger,
    context: BoltContext,
    set_status: SetStatus,
    get_thread_context: GetThreadContext,
    client: WebClient,
    say: Say,
):
    try:
        # set a random thinking message every time we start processing a user message
        set_status(thinking_messages[int(random() * len(thinking_messages))])
        thread_context = get_thread_context()
        if thread_context is not None:
            # If the thread context has changed, we may need to update our state
            channel_id = thread_context.get("channel_id")
            say(f"The context of this thread has changed to a new channel <#{channel_id}>. How can I assist you?")
    except Exception as e:
        logger.exception(f"Failed to handle a thread context change event: {e}")
        say(f":warning: Something went wrong! ({e})")
