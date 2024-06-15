import re
import textwrap

import requests
from slack_sdk import WebClient


class slack_client:
    def __init__(self, **kwargs):
        self.client = WebClient(token=kwargs.get("access_token"))
        self.channel_id = kwargs.get("channel_id")
        self.max_content_length = kwargs.get("max_content_length", 40000)

    def content_in_chunks(content, max_chunk_length):
        paragraphs = content.split("\n\n\n")
        for p in paragraphs:
            for chunk in textwrap.wrap(p.strip("\n"), max_chunk_length, replace_whitespace=False):
                yield chunk

    def wrap_text_with_index(self, content):
        if len(content) <= self.max_content_length:
            return [content]
        urls = re.findall(r"https?://\S+", content)
        placeholder_content = re.sub(
            r"https?://\S+", lambda m: "~" * len(m.group()), content
        )
        wrapped_lines = list(
            self.content_in_chunks(placeholder_content, self.max_content_length - 8)
        )
        final_lines = []
        url_index = 0
        for i, line in enumerate(wrapped_lines, 1):
            while "~~~~~~~~~~" in line and url_index < len(urls):
                placeholder = "~" * len(urls[url_index])
                line = line.replace(placeholder, urls[url_index], 1)
                url_index += 1
            final_lines.append(f"{line} ({i}/{len(wrapped_lines)})")
        return final_lines

    def format_content(self, content, mentions, hashtags, images, **kwargs):
        warnings = ""
        chunks = self.wrap_text_with_index(content)

        formatted_content = {
            "body": "\n\n".join(chunks),
            "images": images,
            "chunks": chunks,
        }
        preview = formatted_content["body"]
        images_preview = "\n".join(
            [f'![{image.get("alt_text", "")}]({image["url"]})' for image in images]
        )
        preview += "\n\n" + images_preview
        return formatted_content, preview, warnings

    def upload_images(self, images):
        uploaded_files = []
        for image in images:
            filename = image["url"].split("/")[-1]

            with requests.get(image["url"]) as response:
                if response.status_code != 200 or not response.headers.get(
                    "Content-Type", ""
                ).startswith("image/"):
                    continue
                image_content = response.content

            response = self.client.files_getUploadURLExternal(
                filename=filename,
                length=len(image_content),
                alt_txt=image["alt_text"] if "alt_text" in image else None,
            )

            with requests.post(
                response["upload_url"], files={"file": image_content}
            ) as upload_response:
                if upload_response.status_code != 200:
                    continue
            uploaded_files.append({"id": response["file_id"]})

        response = self.client.files_completeUploadExternal(
            files=uploaded_files, channel_id=self.channel_id
        )
        return response

    def create_post(self, content, **kwargs):
        link = None
        parent_ts = None
        for text in content["chunks"]:
            response = self.client.chat_postMessage(
                channel=self.channel_id,
                text=text,
                thread_ts=parent_ts if parent_ts else None,
            )
            if not parent_ts:
                parent_ts = response["ts"]
                link = self.client.chat_getPermalink(
                    channel=self.channel_id, message_ts=parent_ts
                )["permalink"]
            if not response["ok"]:
                return False, None
        if content["images"]:
            response = self.upload_images(content["images"])
            if not response["ok"]:
                return False, None
        return True, link
