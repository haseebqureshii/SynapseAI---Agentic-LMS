from google import genai
from google.genai import types
import base64
import mimetypes
import os

class GeminiService:
    def __init__(self, api_key):
        # API key is now passed directly to the Client constructor
        self.client = genai.Client(api_key=api_key) # <- Changed initialization
        self.model = self.client.models.get('gemini-pro-vision') # Or 'gemini-1.5-flash' etc.

    def _prepare_pdf_part(self, file_path):
        """Prepares a PDF file as a Google Generative AI Part object."""
        try:
            mime_type, _ = mimetypes.guess_type(file_path)
            if not mime_type or not mime_type.startswith('application/pdf'):
                raise ValueError(f"File {file_path} is not a PDF or MIME type is unknown.")

            with open(file_path, 'rb') as f:
                file_bytes = f.read()

            # Direct instantiation with keyword arguments for types.Part
            return types.Part(data=file_bytes, mime_type=mime_type) # <- Changed Part creation
        except Exception as e:
            print(f"Error preparing PDF part: {e}")
            raise

    def get_assignment_feedback(self, student_submission_pdf_path, professor_solution_pdf_path, course_name=""):
        """
        Generates feedback for a student's assignment.
        Assumes PDF paths are accessible locally on the server.
        """
        prompt = f"""
        You are an AI teaching assistant for the course {course_name}.
        Your task is to compare a student's submitted assignment with the provided correct solution.
        Please provide detailed feedback to the student based on the comparison.

        **Instructions:**
        1.  **Correctness Check:** Identify parts of the student's solution that are correct and incorrect.
        2.  **Specific Errors:** Point out any errors or missing steps clearly, referencing the relevant sections/questions if possible.
        3.  **Areas for Improvement:** Suggest specific areas or concepts the student needs to review.
        4.  **Positive Reinforcement:** Start with positive feedback before constructive criticism.
        5.  **Structure:** Present the feedback as a comprehensive report with clear headings.

        ---
        **Input:**
        Student Submission: [First PDF provided]
        Correct Solution: [Second PDF provided]
        ---
        **Feedback Report:**
        """
        try:
            student_pdf_part = self._prepare_pdf_part(student_submission_pdf_path)
            solution_pdf_part = self._prepare_pdf_part(professor_solution_pdf_path)

            contents = [
                prompt,
                student_pdf_part,
                solution_pdf_part
            ]

            response = self.model.generate_content(
                contents,
                safety_settings={
                    "HARM_CATEGORY_HARASSMENT": "BLOCK_NONE",
                    "HARM_CATEGORY_HATE_SPEECH": "BLOCK_NONE",
                    "HARM_CATEGORY_SEXUALLY_EXPLICIT": "BLOCK_NONE",
                    "HARM_CATEGORY_DANGEROUS_CONTENT": "BLOCK_NONE",
                }
            )
            return response.text
        except Exception as e:
            print(f"Error generating assignment feedback: {e}")
            return f"An error occurred while generating feedback: {e}"

    def perform_integrity_check(self, student_submission_pdf_path):
        """
        Performs a basic integrity check on a single student's submission.
        This is a conceptual starting point; robust integrity checks are complex.
        """
        prompt = f"""
        Analyze the attached student assignment submission for any unusual patterns that might suggest academic integrity concerns.
        Look for:
        -   Sudden changes in writing style or problem-solving approach.
        -   Inclusion of concepts not yet covered in the course material.
        -   Any indications of direct copy-pasting from external sources (though direct detection is hard without source comparison).
        -   Uncharacteristic perfection or errors.

        Provide a concise report indicating any flags, with explanations. If no flags are found, state so clearly.
        """
        try:
            student_pdf_part = self._prepare_pdf_part(student_submission_pdf_path)
            contents = [prompt, student_pdf_part]
            response = self.model.generate_content(contents)
            return response.text
        except Exception as e:
            print(f"Error performing integrity check: {e}")
            return f"An error occurred during integrity check: {e}"

    def get_class_performance_summary(self, individual_reports: list):
        """
        Generates a summary of class performance from a list of individual student reports.
        `individual_reports` would be strings of the feedback generated earlier.
        """
        combined_reports = "\n---\n".join(individual_reports)
        prompt = f"""
        Here are individual feedback reports for a class's assignment.
        Please analyze these reports and provide an overall summary of the class's performance.
        Identify:
        -   Common areas of strength.
        -   Common areas where students struggled (e.g., specific topics, types of problems).
        -   Any noticeable trends or patterns across the class.
        -   Suggestions for the professor based on these insights (e.g., topics to revisit, common misconceptions).

        ---
        Individual Student Reports:
        {combined_reports}
        ---
        Class Performance Summary:
        """
        try:
            response = self.model.generate_content(prompt)
            return response.text
        except Exception as e:
            print(f"Error generating class summary: {e}")
            return f"An error occurred while generating class summary: {e}"