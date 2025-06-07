import tkinter as tk
from tkinter import ttk, messagebox
import yt_dlp
import os
import subprocess
from fpdf import FPDF
import threading
import re
from urllib.parse import urlparse, parse_qs
import time
import math
from transformers import pipeline
import nltk
from nltk.tokenize import sent_tokenize

class YouTubeToPDFConverter(tk.Tk):
    def __init__(self):
        super().__init__()

        # Download required NLTK data
        try:
            nltk.data.find('tokenizers/punkt')
        except LookupError:
            nltk.download('punkt')

        # Initialize the transcription and summarization models
        self.transcriber = pipeline("automatic-speech-recognition", model="openai/whisper-small")
        self.summarizer = pipeline("summarization", model="facebook/bart-large-cnn")

        # Window setup
        self.title("YouTube Video Notes Converter")
        self.geometry("600x500")
        self.configure(bg="#f0f0f0")

        # Create main frame
        self.main_frame = ttk.Frame(self, padding="20")
        self.main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        # Style configuration
        style = ttk.Style()
        style.configure("Custom.TLabel", padding=5)
        style.configure("Custom.TButton", padding=10)

        # YouTube URL input
        ttk.Label(self.main_frame, text="YouTube URL:", style="Custom.TLabel").grid(row=0, column=0, sticky=tk.W)
        self.url_var = tk.StringVar()
        self.url_entry = ttk.Entry(self.main_frame, textvariable=self.url_var, width=50)
        self.url_entry.grid(row=0, column=1, padx=5, pady=5, sticky=tk.W)

        # Progress display
        self.progress_var = tk.StringVar(value="Ready to convert...")
        ttk.Label(self.main_frame, textvariable=self.progress_var, style="Custom.TLabel").grid(row=1, column=0, columnspan=2, pady=20)

        # Progress bar
        self.progress_bar = ttk.Progressbar(self.main_frame, length=400, mode='determinate')
        self.progress_bar.grid(row=2, column=0, columnspan=2, pady=10)

        # Convert button
        self.convert_button = ttk.Button(
            self.main_frame, 
            text="Convert to PDF", 
            command=self.start_conversion,
            style="Custom.TButton"
        )
        self.convert_button.grid(row=3, column=0, columnspan=2, pady=20)

        # Status text
        self.status_text = tk.Text(self.main_frame, height=5, width=50)
        self.status_text.grid(row=4, column=0, columnspan=2, pady=10)
        self.status_text.insert(tk.END, "Instructions:\n1. Paste a valid YouTube URL\n2. Click 'Convert to PDF'")
        self.status_text.config(state='disabled')

    def update_progress(self, message, progress_value):
        self.progress_var.set(message)
        self.progress_bar['value'] = progress_value
        self.update_idletasks()

    def update_status(self, message):
        self.status_text.config(state='normal')
        self.status_text.insert(tk.END, "\n" + message)
        self.status_text.see(tk.END)
        self.status_text.config(state='disabled')

    def transcribe_audio(self, file_path):
        try:
            # Check if file exists
            if not os.path.exists(file_path):
                raise Exception(f"Audio file not found at {file_path}")

            self.update_status(f"Transcribing audio file...")
            # Transcribe using local Whisper model
            result = self.transcriber(file_path)
            return result["text"]

        except Exception as e:
            error_msg = str(e)
            self.update_status(f"Transcription error: {error_msg}")
            messagebox.showerror("Transcription Error", f"Failed to transcribe audio: {error_msg}")
            return None

    def download_youtube_audio(self, url, output_path='audio'):
    try:
        if not os.path.exists(output_path):
            os.makedirs(output_path)

            output_template = os.path.join(output_path, 'audio.%(ext)s')

            ydl_opts = {
                'format': 'bestaudio/best',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'wav',
                }],
                'outtmpl': output_template,
                'progress_hooks': [self.my_hook],
                'quiet': True,
                'no_warnings': True
            }

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                self.update_status("Extracting video information...")
                info = ydl.extract_info(url, download=False)
                
                # Check video duration
                duration = info.get('duration', 0)
                if duration > 3600:  # 1 hour
                    raise Exception("Video is too long. Please use a video shorter than 1 hour.")
                
                self.update_status(f"Downloading: {info.get('title', 'Video')}")
                ydl.download([url])

        wav_file = os.path.join(output_path, 'audio.wav')
            if not os.path.exists(wav_file):
                raise Exception("Failed to convert to WAV format")
        
        return wav_file

    except Exception as e:
            error_msg = str(e)
            detailed_msg = f"Error downloading video: {error_msg}\nPlease try:\n- Checking if the video is available\n- Verifying your internet connection"
            self.update_status(detailed_msg)
            messagebox.showerror("Error", detailed_msg)
        return None

    def my_hook(self, d):
        if d['status'] == 'downloading':
            if 'total_bytes' in d and 'downloaded_bytes' in d:
                progress = (d['downloaded_bytes'] / d['total_bytes']) * 100
                self.update_status(f"Downloading: {progress:.1f}% complete")
        elif d['status'] == 'finished':
            self.update_status("Download completed, processing file...")

    def summarize_text(self, text):
        try:
            self.update_status("Generating summary...")
            
            # Split text into sentences
            sentences = sent_tokenize(text)
            
            # Split into chunks of roughly 1000 characters
            chunks = []
            current_chunk = []
            current_length = 0
            
            for sentence in sentences:
                sentence_length = len(sentence)
                if current_length + sentence_length > 1000:
                    # Join the current chunk and add it to chunks
                    chunks.append(' '.join(current_chunk))
                    current_chunk = [sentence]
                    current_length = sentence_length
                else:
                    current_chunk.append(sentence)
                    current_length += sentence_length
            
            # Add the last chunk if it exists
            if current_chunk:
                chunks.append(' '.join(current_chunk))
            
            # Summarize each chunk
            summaries = []
            for i, chunk in enumerate(chunks):
                self.update_status(f"Summarizing part {i+1} of {len(chunks)}...")
                summary = self.summarizer(chunk, max_length=130, min_length=30, do_sample=False)
                summaries.append(summary[0]['summary_text'])
            
            # Combine summaries with formatting
            formatted_summary = "# Video Summary\n\n"
            for i, summary in enumerate(summaries, 1):
                formatted_summary += f"## Part {i}\n\n"
                formatted_summary += f"{summary}\n\n"
            
            return formatted_summary

    except Exception as e:
            error_msg = str(e)
            self.update_status(f"Summarization error: {error_msg}")
            messagebox.showerror("Summarization Error", f"Failed to generate summary: {error_msg}")
        return None

    def save_to_pdf(self, text, filename="notes.pdf"):
    try:
        pdf = FPDF()
        pdf.add_page()
        pdf.set_auto_page_break(auto=True, margin=15)
        pdf.set_font("Arial", size=12)
            
            # Add title
            pdf.set_font("Arial", 'B', size=16)
            pdf.cell(0, 10, "YouTube Video Notes", ln=True, align='C')
            pdf.ln(10)
            
            # Reset font for content
            pdf.set_font("Arial", size=12)
            
            # Add content
        for line in text.split('\n'):
                if line.strip().startswith('#'):  # Heading
                    pdf.set_font("Arial", 'B', size=14)
                    pdf.multi_cell(0, 10, line.strip('# '))
                    pdf.set_font("Arial", size=12)
                else:
            pdf.multi_cell(0, 10, line)
            
        pdf.output(filename)
        return True
    except Exception as e:
            self.update_status(f"PDF creation error: {str(e)}")
        return False

    def convert_process(self, url):
        try:
            # Download audio
            self.update_progress("Downloading audio...", 20)
            self.update_status("Downloading video audio...")
            audio_file = self.download_youtube_audio(url)
            if not audio_file:
                raise Exception("Failed to download audio")

            # Transcribe
            self.update_progress("Transcribing audio...", 40)
            self.update_status("Transcribing audio to text...")
            transcript = self.transcribe_audio(audio_file)
            if not transcript:
                raise Exception("Failed to transcribe audio")

            # Summarize
            self.update_progress("Summarizing text...", 60)
            self.update_status("Generating summary...")
            summary = self.summarize_text(transcript)
            if not summary:
                raise Exception("Failed to summarize text")

            # Save PDF
            self.update_progress("Creating PDF...", 80)
            self.update_status("Creating PDF document...")
            if self.save_to_pdf(summary):
                self.update_progress("✅ Notes saved as notes.pdf", 100)
                self.update_status("Success! Notes saved as notes.pdf")
                messagebox.showinfo("Success", "PDF has been created successfully!")
            else:
                raise Exception("Failed to save PDF")

        except Exception as e:
            self.update_progress(f"Error: {str(e)}", 0)
            self.update_status(f"Error: {str(e)}")
            messagebox.showerror("Error", str(e))

        finally:
            # Re-enable the convert button
            self.convert_button['state'] = 'normal'

    def validate_youtube_url(self, url):
        """Basic YouTube URL validation"""
        patterns = [
            r'^https?://(?:www\.)?youtube\.com/watch\?v=[\w-]+',
            r'^https?://youtu\.be/[\w-]+',
            r'^https?://(?:www\.)?youtube\.com/v/[\w-]+',
            r'^https?://(?:www\.)?youtube\.com/embed/[\w-]+'
        ]
        return any(re.match(pattern, url) for pattern in patterns)

    def start_conversion(self):
        # Validate inputs
        url = self.url_var.get().strip()

        if not url:
            messagebox.showerror("Error", "Please enter a YouTube URL")
        return
        if not self.validate_youtube_url(url):
            messagebox.showerror("Error", "Invalid YouTube URL format")
        return
    
        # Disable the convert button
        self.convert_button['state'] = 'disabled'
        
        # Start conversion in a separate thread
        thread = threading.Thread(target=self.convert_process, args=(url,))
        thread.daemon = True
        thread.start()

if __name__ == "__main__":
    app = YouTubeToPDFConverter()
    app.mainloop()
