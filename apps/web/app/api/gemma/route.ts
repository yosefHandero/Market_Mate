import { NextResponse } from 'next/server';
import { GoogleGenAI } from '@google/genai';

const ai = new GoogleGenAI({
  apiKey: process.env.GEMMA_API_KEY,
});
export async function GET() {
  try {
    const response = await ai.models.generateContent({
      model: 'gemma-4-31b-it',
      contents: 'Give me 3 short app ideas.',
    });

    return NextResponse.json({ text: response.text });
  } catch (error) {
    console.error('Gemma GET error:', error);
    return NextResponse.json({ error: 'Gemma test failed' }, { status: 500 });
  }
}
export async function POST(req: Request) {
  try {
    const { prompt } = await req.json();

    const response = await ai.models.generateContent({
      model: 'gemma-4-31b-it',
      contents: prompt,
    });

    return NextResponse.json({ text: response.text });
  } catch (error) {
    console.error('Gemma API error:', error);
    return NextResponse.json({ error: 'Failed to generate' }, { status: 500 });
  }
}
