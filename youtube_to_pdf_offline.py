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
import torch
from faster_whisper import WhisperModel

class YouTubeToPDFConverter(tk.Tk):
    def __init__(self):
        super().__init__()

        # Window setup
        self.title(" Video Notes Converter (Offline)")
        self.geometry("600x500")
        self.configure(bg="#f0f0f0")

        # Create main frame
        self.main_frame = ttk.Frame(self, padding="20")
        self.main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        # Style configuration
        style = ttk.Style()
        style.configure("Custom.TLabel", padding=5)
        style.configure("Custom.TButton", padding=10)

        # Status text - create this first so we can use it for updates
        self.status_text = tk.Text(self.main_frame, height=5, width=50)
        self.status_text.grid(row=6, column=0, columnspan=2, pady=10)
        self.status_text.insert(tk.END, "Instructions:\n1. Paste a valid YouTube URL\n2. Set maximum duration (default 60 minutes)\n3. Set chunk size for processing (default 10 minutes)\n4. Click 'Convert to PDF'")
        self.status_text.config(state='disabled')

        # Download DejaVu font if not present
        font_path = 'DejaVuSansCondensed.ttf'
        if not os.path.exists(font_path):
            import urllib.request
            font_url = 'https://github.com/dejavu-fonts/dejavu-fonts/raw/master/ttf/DejaVuSansCondensed.ttf'
            try:
                urllib.request.urlretrieve(font_url, font_path)
                self.update_status("Downloaded required font file")
            except Exception as e:
                self.update_status(f"Warning: Could not download font: {str(e)}")

        # YouTube URL input
        ttk.Label(self.main_frame, text="YouTube URL:", style="Custom.TLabel").grid(row=0, column=0, sticky=tk.W)
        self.url_var = tk.StringVar()
        self.url_entry = ttk.Entry(self.main_frame, textvariable=self.url_var, width=50)
        self.url_entry.grid(row=0, column=1, padx=5, pady=5, sticky=tk.W)

        # Duration limit input
        ttk.Label(self.main_frame, text="Max Duration (minutes):", style="Custom.TLabel").grid(row=1, column=0, sticky=tk.W)
        self.duration_var = tk.StringVar(value="60")  # Increased to 60 minutes
        self.duration_entry = ttk.Entry(self.main_frame, textvariable=self.duration_var, width=10)
        self.duration_entry.grid(row=1, column=1, padx=5, pady=5, sticky=tk.W)

        # Add chunk size option
        ttk.Label(self.main_frame, text="Chunk Size (minutes):", style="Custom.TLabel").grid(row=2, column=0, sticky=tk.W)
        self.chunk_size_var = tk.StringVar(value="10")
        self.chunk_size_entry = ttk.Entry(self.main_frame, textvariable=self.chunk_size_var, width=10)
        self.chunk_size_entry.grid(row=2, column=1, padx=5, pady=5, sticky=tk.W)

        # Progress display
        self.progress_var = tk.StringVar(value="Ready to convert...")
        ttk.Label(self.main_frame, textvariable=self.progress_var, style="Custom.TLabel").grid(row=3, column=0, columnspan=2, pady=20)

        # Progress bar
        self.progress_bar = ttk.Progressbar(self.main_frame, length=400, mode='determinate')
        self.progress_bar.grid(row=4, column=0, columnspan=2, pady=10)

        # Convert button
        self.convert_button = ttk.Button(
            self.main_frame, 
            text="Convert to PDF", 
            command=self.start_conversion,
            style="Custom.TButton"
        )
        self.convert_button.grid(row=5, column=0, columnspan=2, pady=20)

        # Download required NLTK data
        try:
            nltk.data.find('tokenizers/punkt')
        except LookupError:
            nltk.download('punkt')

        # Initialize the models
        self.update_status("Loading models (this may take a moment)...")
        self.summarizer = pipeline("summarization", model="facebook/bart-large-cnn")
        self.transcriber = WhisperModel("tiny", device="cpu", compute_type="int8", num_workers=4)
        self.update_status("Models loaded successfully!")

    def update_progress(self, message, progress_value):
        self.progress_var.set(message)
        self.progress_bar['value'] = progress_value
        self.update_idletasks()

    def update_status(self, message):
        self.status_text.config(state='normal')
        self.status_text.insert(tk.END, "\n" + message)
        self.status_text.see(tk.END)
        self.status_text.config(state='disabled')
        self.update_idletasks()

    def process_audio_chunk(self, audio_file, start_time, duration):
        """Process a chunk of audio file"""
        try:
            output_chunk = f"temp_chunk_{start_time}.wav"
            
            # Use ffmpeg to extract chunk
            cmd = f'ffmpeg -y -i "{audio_file}" -ss {start_time} -t {duration} -acodec pcm_s16le -ar 16000 -ac 1 "{output_chunk}" -loglevel error'
            subprocess.run(cmd, shell=True, check=True)
            
            if not os.path.exists(output_chunk):
                raise Exception(f"Failed to create chunk at {start_time}")
            
            # Transcribe chunk
            segments, _ = self.transcriber.transcribe(
                output_chunk,
                beam_size=1,
                best_of=1,
                temperature=0.0,
                vad_filter=True,
                vad_parameters=dict(min_silence_duration_ms=700, speech_pad_ms=200),
                initial_prompt="This is a YouTube video transcription.",
                condition_on_previous_text=False
            )
            
            # Clean up chunk file
            try:
                os.remove(output_chunk)
            except:
                pass
                
            return " ".join(segment.text for segment in segments)
            
        except Exception as e:
            self.update_status(f"Warning: Error processing chunk at {start_time}: {str(e)}")
            return ""

    def download_youtube_audio(self, url, output_path='audio'):
        try:
            if not os.path.exists(output_path):
                os.makedirs(output_path)

            output_template = os.path.join(output_path, 'audio.%(ext)s')

            # Get max duration from input with better error handling
            try:
                max_duration = float(self.duration_var.get()) * 60  # Convert to seconds
                if max_duration <= 0:
                    max_duration = 3600  # Default 60 minutes if invalid input
                    self.duration_var.set("60")
            except ValueError:
                max_duration = 3600  # Default 60 minutes if invalid input
                self.duration_var.set("60")

            ydl_opts = {
                'format': 'worstaudio/worst',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'wav',
                    'preferredquality': '32',
                }],
                'outtmpl': output_template,
                'progress_hooks': [self.my_hook],
                'quiet': True,
                'no_warnings': True
            }

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                self.update_status("Extracting video information...")
                info = ydl.extract_info(url, download=False)
                
                duration = info.get('duration', 0)
                if duration > max_duration:
                    minutes = max_duration / 60
                    video_minutes = duration / 60
                    raise Exception(
                        f"Video is {video_minutes:.1f} minutes long. "
                        f"Please use a video shorter than {minutes:.1f} minutes or "
                        f"increase the duration limit in the 'Max Duration' field."
                    )
                
                self.update_status(f"Downloading: {info.get('title', 'Video')}")
                ydl.download([url])

            wav_file = os.path.join(output_path, 'audio.wav')
            if not os.path.exists(wav_file):
                raise Exception("Failed to convert to WAV format")

            return wav_file

        except Exception as e:
            error_msg = str(e)
            self.update_status(f"Error downloading video: {error_msg}")
            messagebox.showerror("Error", error_msg)
            return None

    def my_hook(self, d):
        if d['status'] == 'downloading':
            if 'total_bytes' in d and 'downloaded_bytes' in d:
                progress = (d['downloaded_bytes'] / d['total_bytes']) * 100
                self.update_status(f"Downloading: {progress:.1f}% complete")
        elif d['status'] == 'finished':
            self.update_status("Download completed, processing file...")

    def transcribe_audio(self, file_path):
        try:
            if not os.path.exists(file_path):
                raise Exception(f"Audio file not found at {file_path}")

            self.update_status("Transcribing audio file...")
            
            # Get chunk size in seconds
            try:
                chunk_size = float(self.chunk_size_var.get()) * 60  # Convert to seconds
                if chunk_size <= 0:
                    chunk_size = 600  # Default 10 minutes if invalid
            except ValueError:
                chunk_size = 600  # Default 10 minutes if invalid
                self.chunk_size_var.set("10")

            # Get audio duration using ffprobe
            cmd = f'ffprobe -i "{file_path}" -show_entries format=duration -v quiet -of csv="p=0"'
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            total_duration = float(result.stdout.strip())
            
            # Process audio in chunks
            chunks = []
            current_time = 0
            
            while current_time < total_duration:
                self.update_status(f"Processing chunk at {current_time/60:.1f} minutes...")
                chunk_duration = min(chunk_size, total_duration - current_time)
                
                chunk_text = self.process_audio_chunk(file_path, current_time, chunk_duration)
                if chunk_text:
                    chunks.append(chunk_text)
                
                current_time += chunk_duration
                progress = (current_time / total_duration) * 100
                self.update_progress(f"Transcribing: {progress:.1f}% complete", progress)

            return " ".join(chunks)

        except Exception as e:
            error_msg = str(e)
            self.update_status(f"Transcription error: {error_msg}")
            messagebox.showerror("Transcription Error", f"Failed to transcribe audio: {error_msg}")
            return None

    def summarize_text(self, text):
        try:
            if not text or len(text.strip()) < 50:
                self.update_status("Text is too short to summarize.")
                return "# Video Summary\n\n" + text

            self.update_status("Generating summary...")
            
            # Clean the text
            text = text.replace('\n', ' ').strip()
            
            # Split text into sentences
            sentences = sent_tokenize(text)
            
            # Split into chunks of roughly 800 characters (reduced from 1000 for better stability)
            chunks = []
            current_chunk = []
            current_length = 0
            min_chunk_length = 200  # Minimum length to attempt summarization
            
            for sentence in sentences:
                sentence_length = len(sentence)
                if current_length + sentence_length > 800:
                    chunk_text = ' '.join(current_chunk)
                    if len(chunk_text) >= min_chunk_length:
                        chunks.append(chunk_text)
                    current_chunk = [sentence]
                    current_length = sentence_length
                else:
                    current_chunk.append(sentence)
                    current_length += sentence_length
            
            # Add the last chunk if it exists and meets minimum length
            last_chunk = ' '.join(current_chunk)
            if last_chunk and len(last_chunk) >= min_chunk_length:
                chunks.append(last_chunk)
            
            # Handle case where no valid chunks were created
            if not chunks:
                return "# Video Summary\n\n" + text
            
            # Summarize each chunk with error handling
            summaries = []
            for i, chunk in enumerate(chunks):
                try:
                    self.update_status(f"Summarizing part {i+1} of {len(chunks)}...")
                    
                    # Add safety checks for chunk length
                    if len(chunk) < min_chunk_length:
                        summaries.append(chunk)
                        continue
                        
                    summary = self.summarizer(
                        chunk,
                        max_length=130,
                        min_length=30,
                        do_sample=False,
                        truncation=True
                    )
                    
                    if summary and len(summary) > 0:
                        summaries.append(summary[0]['summary_text'])
                    else:
                        summaries.append(chunk)  # Use original text if summarization fails
                        
                except Exception as chunk_error:
                    self.update_status(f"Warning: Could not summarize part {i+1}, using original text")
                    summaries.append(chunk)  # Fallback to original text
            
            # Combine summaries with formatting
            formatted_summary = "# Video Summary\n\n"
            
            if len(summaries) == 1:
                formatted_summary += summaries[0]
            else:
                for i, summary in enumerate(summaries, 1):
                    formatted_summary += f"## Part {i}\n\n"
                    formatted_summary += f"{summary}\n\n"
            
            return formatted_summary

        except Exception as e:
            error_msg = f"Summarization error: {str(e)}"
            self.update_status(error_msg)
            messagebox.showerror("Summarization Error", error_msg)
            # Return original text as fallback
            return "# Video Summary\n\n" + text

    def download_font(self):
        """Download the DejaVu font if not present"""
        font_path = 'DejaVuSansCondensed.ttf'
        if not os.path.exists(font_path):
            import urllib.request
            font_url = 'https://github.com/dejavu-fonts/dejavu-fonts/raw/master/ttf/DejaVuSansCondensed.ttf'
            try:
                urllib.request.urlretrieve(font_url, font_path)
                self.update_status("Downloaded required font file")
                return True
            except Exception as e:
                self.update_status(f"Warning: Could not download font: {str(e)}")
                return False
        return True

    def save_to_pdf(self, text, filename="notes.pdf"):
        try:
            # Download font if needed
            self.download_font()
            
            # First, ensure any existing PDF is not locked
            if os.path.exists(filename):
                try:
                    os.remove(filename)
                except:
                    pass

            pdf = FPDF()
            pdf.add_page()
            pdf.set_auto_page_break(auto=True, margin=15)
            
            # Use basic ASCII font if DejaVu is not available
            if os.path.exists('DejaVuSansCondensed.ttf'):
                pdf.add_font('DejaVu', '', 'DejaVuSansCondensed.ttf', uni=True)
                font_to_use = 'DejaVu'
            else:
                font_to_use = 'Arial'
            
            pdf.set_font(font_to_use, size=12)
            
            # Add title
            pdf.set_font(font_to_use, size=16)
            pdf.cell(0, 10, " Video transcripted Notes", ln=True, align='C')
            pdf.ln(10)
            
            # Reset font for content
            pdf.set_font(font_to_use, size=12)
            
            # Clean and encode text - remove problematic characters
            clean_text = ""
            for char in text:
                try:
                    # Test if character can be encoded
                    char.encode('latin-1')
                    clean_text += char
                except UnicodeEncodeError:
                    # Replace problematic characters with closest ASCII equivalent
                    clean_text += '?'
            
            # Split into paragraphs and add content
            paragraphs = clean_text.split('\n')
            for para in paragraphs:
                if para.strip().startswith('#'):  # Heading
                    pdf.set_font(font_to_use, size=14)
                    pdf.multi_cell(0, 10, para.strip('# '))
                    pdf.set_font(font_to_use, size=12)
                else:
                    pdf.multi_cell(0, 10, para)
            
            # Try multiple save methods
            try:
                pdf.output(filename, 'F')  # Try direct file output
            except Exception as e1:
                try:
                    # Try binary write method
                    with open(filename, 'wb') as f:
                        pdf.output(f)
                except Exception as e2:
                    # Try writing to temporary file first
                    temp_file = 'temp_output.pdf'
                    pdf.output(temp_file)
                    import shutil
                    shutil.move(temp_file, filename)
            
            return True
            
        except Exception as e:
            self.update_status(f"PDF creation error: {str(e)}")
            return False

    def retry_remove(self, path, max_attempts=5):
        """Helper function to retry removal with delays"""
        import time
        for attempt in range(max_attempts):
            try:
                if os.path.isfile(path):
                    os.chmod(path, 0o777)  # Give full permissions
                    os.remove(path)
                elif os.path.isdir(path):
                    os.chmod(path, 0o777)  # Give full permissions
                    if not os.listdir(path):  # Only if directory is empty
                        os.rmdir(path)
                return True
            except Exception as e:
                if attempt < max_attempts - 1:
                    time.sleep(1)  # Wait before retry
                    continue
                return False
        return False

    def cleanup_files(self):
        """Clean up temporary files with proper error handling"""
        try:
            # Clean up audio directory
            if os.path.exists('audio'):
                # First, try to remove files in the directory
                for file in os.listdir('audio'):
                    file_path = os.path.join('audio', file)
                    if not self.retry_remove(file_path):
                        self.update_status(f"Warning: Could not remove file {file}")
                
                # Then try to remove the directory itself
                if not self.retry_remove('audio'):
                    self.update_status("Warning: Could not remove audio directory")
            
            # Clean up any remaining temp chunks
            for file in os.listdir('.'):
                if file.startswith('temp_chunk_') and file.endswith('.wav'):
                    if not self.retry_remove(file):
                        self.update_status(f"Warning: Could not remove temp file {file}")
                        
        except Exception as e:
            self.update_status(f"Warning: Cleanup error: {str(e)}")

    def convert_process(self, url):
        audio_file = None
        try:
            # Ensure cleanup from any previous runs
            self.cleanup_files()
            
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
            
            # Basic transcript validation
            if len(transcript.strip()) < 10:
                raise Exception("Transcription produced empty or very short text")

            # Summarize
            self.update_progress("Summarizing text...", 60)
            self.update_status("Generating summary...")
            summary = self.summarize_text(transcript)
            if not summary:
                self.update_status("Warning: Summarization failed, using original transcript")
                summary = "# Video Transcript\n\n" + transcript

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
            error_msg = str(e)
            self.update_progress(f"Error: {error_msg}", 0)
            self.update_status(f"Error: {error_msg}")
            messagebox.showerror("Error", error_msg)

        finally:
            # Cleanup temporary files with retries
            self.cleanup_files()
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