require('dotenv').config();

if (!process.env.TOKEN) {
    console.error("ERROR: Discord bot token (TOKEN) not found in environment variables.");
    console.error("Please create a .env file with TOKEN=YOUR_BOT_TOKEN.");
    process.exit(1);
}
if (!process.env.ADMIN_API_KEY) {
    console.error("WARNING: Admin API key (ADMIN_API_KEY) not found in environment variables. Admin commands will fail.");
}


const { Client, GatewayIntentBits, ActionRowBuilder, ButtonBuilder, ButtonStyle, EmbedBuilder, PermissionsBitField } = require('discord.js');
const { REST } = require('@discordjs/rest');
const { Routes } = require('discord-api-types/v10');
const { createCanvas, loadImage } = require('canvas');
const { OpenAI } = require('openai');

const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const CONFIG_FILE_PATH = path.join(__dirname, 'config.json');

function readConfig() {
    try {
        if (fs.existsSync(CONFIG_FILE_PATH)) {
            const data = fs.readFileSync(CONFIG_FILE_PATH, 'utf8');
            return JSON.parse(data);
        }
    } catch (error) {
        console.error("Error reading config file:", error);
    }
    return { theme: 'default', allowedChannels: [] };
}

function writeConfig(configData) {
    try {
        fs.writeFileSync(CONFIG_FILE_PATH, JSON.stringify(configData, null, 2), 'utf8');
        console.log("Config saved successfully.");
    } catch (error) {
        console.error("Error writing config file:", error);
    }
}

const normalizeChannelName = (name) => name.replace(/^\.+|\.+$/g, '');

function removeEveryoneHereMentions(text) {

  const mentionRegex = /@(?:everyone|here)|<@&\d+>/gi;
  return text.replace(mentionRegex, '[mention]');
}


const IMAGE_THEMES = {
    default: {
        bgStart: '#2c3e50',
        bgEnd: '#3498db',
        textColor: '#ffffff'
    },
    sunset: {
        bgStart: '#ff7e5f',
        bgEnd: '#feb47b',
        textColor: '#333333'
    },
    forest: {
        bgStart: '#134E5E',
        bgEnd: '#71B280',
        textColor: '#ffffff'
    },
    ocean: {
        bgStart: '#005AA7',
        bgEnd: '#FFFDE4',
        textColor: '#003366'
    }
};
const openai = new OpenAI({
  apiKey: process.env.OPENAI_API_KEY || 'sk-2e4390ef9a39b127eddc152ea5380c601f0e84f924a3a1a5',
  baseURL: "https://api.exomlapi.com/v1"
});

async function makeExoMLRequest(prompt, model, onChunk, imageUrls = null) {
  try {
    let messageContent;
    
    if (imageUrls && imageUrls.length > 0) {
      messageContent = [
        {
          type: "text",
          text: prompt
        }
      ];
      
      for (const imageUrl of imageUrls) {
        messageContent.push({
          type: "image_url",
          image_url: {
            url: imageUrl
          }
        });
      }
    } else {
      messageContent = prompt;
    }
    
    const response = await fetch('https://api.exomlapi.com/v1/chat/completions', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${process.env.OPENAI_API_KEY || 'sk-2e4390ef9a39b127eddc152ea5380c601f0e84f924a3a1a5'}`
      },
      body: JSON.stringify({
        model,
        messages: [{
          role: "user",
          content: messageContent
        }],
        stream: true,
        max_tokens: 1000,
      })
    });

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }

    let fullResponse = '';
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          const trimmedLine = line.trim();
          if (!trimmedLine) continue;
          
          if (trimmedLine.startsWith('data: ')) {
            const dataStr = trimmedLine.slice(6);
            
            if (dataStr === '[DONE]' || dataStr.includes('"type": "ping"')) {
              continue;
            }
            
            try {
              const data = JSON.parse(dataStr);
              const content = data.choices?.[0]?.delta?.content || '';
              
              if (content) {
                fullResponse += content;
                if (onChunk) onChunk(content);
              }
            } catch (parseError) {
              console.warn('Failed to parse streaming chunk, ignoring:', parseError.message);
              continue;
            }
          }
        }
      }
    } finally {
      reader.releaseLock();
    }
    
    if (!fullResponse) {
      return 'The AI service returned an empty response. Please try again.';
    }
    
    return fullResponse;
  } catch (error) {
    console.error('OpenAI API error:', error);
    
    if (error?.response?.status === 502) {
      return 'The AI service is currently unavailable. Please try again later.';
    }
    
    if (error?.message?.includes('invalid json') || error?.type === 'invalid-json') {
      return 'The AI service returned an invalid response. Please try again.';
    }
    
    return 'Sorry, there was an error processing your request.';
  }
}

async function makeExoMLResponseRequest(prompt, model, onChunk, imageUrls = null) {
  try {
    if (imageUrls && imageUrls.length > 0) {
      console.warn('[Responses API] Image attachments not supported on v1/responses endpoint, using text only');
    }
    
    const requestBody = {
      model: model,
      input: prompt
    };
    
    if (model.includes('deep-research')) {
      requestBody.tools = [
        {
          type: "web_search_preview"
        }
      ];
    }
    
    console.log('[Responses API] Request URL:', 'https://api.exomlapi.com/v1/responses');
    console.log('[Responses API] Request body:', JSON.stringify(requestBody, null, 2));
    console.log('[Responses API] Request headers:', {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${(process.env.OPENAI_API_KEY || 'sk-2e4390ef9a39b127eddc152ea5380c601f0e84f924a3a1a5').substring(0, 10)}...`
    });
    
    const response = await fetch('https://api.exomlapi.com/v1/responses', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${process.env.OPENAI_API_KEY || 'sk-2e4390ef9a39b127eddc152ea5380c601f0e84f924a3a1a5'}`
      },
      body: JSON.stringify(requestBody)
    });

    console.log('[Responses API] Response status:', response.status);
    console.log('[Responses API] Response statusText:', response.statusText);
    console.log('[Responses API] Response headers:', Object.fromEntries(response.headers.entries()));

    let responseText;
    try {
      responseText = await response.text();
      console.log('[Responses API] Raw response body:', responseText);
    } catch (textError) {
      console.error('[Responses API] Error reading response text:', textError);
      responseText = '';
    }

    if (!response.ok) {
      console.error('[Responses API] HTTP Error - Status:', response.status, 'StatusText:', response.statusText);
      console.error('[Responses API] Error response body:', responseText);
      throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }

    let responseData;
    try {
      responseData = JSON.parse(responseText);
      console.log('[Responses API] Parsed response data:', JSON.stringify(responseData, null, 2));
    } catch (parseError) {
      console.error('[Responses API] JSON parsing error:', parseError);
      console.error('[Responses API] Raw response that failed to parse:', responseText);
      return 'The AI service returned an invalid JSON response. Please try again.';
    }
    
    let extractedText = "";
    
    if (responseData && responseData.output && Array.isArray(responseData.output)) {
      console.log('[Responses API] Processing new response format with output array');
      for (const outputItem of responseData.output) {
        if (outputItem && typeof outputItem === 'object' && outputItem.type === 'message') {
          const contentArray = outputItem.content;
          if (Array.isArray(contentArray)) {
            for (const contentItem of contentArray) {
              if (contentItem && typeof contentItem === 'object' && contentItem.type === 'output_text') {
                const textContent = contentItem.text;
                if (typeof textContent === 'string') {
                  extractedText += textContent;
                }
              }
            }
          }
        }
      }
    } else if (responseData && responseData.output_text && typeof responseData.output_text === 'string') {
      console.log('[Responses API] Using legacy output_text field');
      extractedText = responseData.output_text;
    }
    
    if (!extractedText) {
      console.error('[Responses API] No text could be extracted from response');
      console.error('[Responses API] Response structure:', responseData);
      return 'The AI service returned an invalid or empty response. Please try again.';
    }
    
    const text = extractedText;
    console.log('[Responses API] Extracted text length:', text.length);
    console.log('[Responses API] Extracted text preview:', text.substring(0, 100) + (text.length > 100 ? '...' : ''));
    
    if (onChunk) {
      onChunk(text);
    }
    
    console.log('[Responses API] Successfully processed response');
    return text;
  } catch (error) {
    console.error('[Responses API] Full error details:', {
      name: error.name,
      message: error.message,
      stack: error.stack,
      cause: error.cause
    });
    
    if (error?.response?.status === 502) {
      return 'The AI service is currently unavailable. Please try again later.';
    }
    
    if (error?.message?.includes('invalid json') || error?.type === 'invalid-json') {
      return 'The AI service returned an invalid response. Please try again.';
    }
    
    return 'Sorry, there was an error processing your request.';
  }
}

function wrapText(context, text, x, y, maxWidth, lineHeight) {
    const words = text.split(' ');
    let line = '';
    let currentY = y;

    for (let n = 0; n < words.length; n++) {
        const testLine = line + words[n] + ' ';
        const metrics = context.measureText(testLine);
        const testWidth = metrics.width;
        if (testWidth > maxWidth && n > 0) {
            context.fillText(line, x, currentY);
            line = words[n] + ' ';
            currentY += lineHeight;
        } else {
            line = testLine;
        }
    }
    context.fillText(line, x, currentY);
    return currentY + lineHeight;
}


async function renderTextToImage(title, content, theme, width = 600, titleFontSize = 30, contentFontSize = 18, padding = 30) {
    const currentTheme = IMAGE_THEMES[theme] || IMAGE_THEMES.default;

    const canvas = createCanvas(width, 100);
    const ctx = canvas.getContext('2d');
    const lineHeightTitle = titleFontSize * 1.2;
    const lineHeightContent = contentFontSize * 1.4;

    let currentY = padding;
    ctx.font = `bold ${titleFontSize}px "Segoe UI", Roboto, sans-serif`;
    currentY = wrapText(ctx, title, padding, currentY + titleFontSize, width - padding * 2, lineHeightTitle);
    currentY += lineHeightContent * 0.5;

    ctx.font = `${contentFontSize}px "Segoe UI", Roboto, sans-serif`;
    const contentLines = content.split('\n');
    for (const line of contentLines) {
         currentY = wrapText(ctx, line.trim(), padding, currentY, width - padding * 2, lineHeightContent);
    }

    const totalHeight = currentY + padding;

    canvas.height = totalHeight;

    const gradient = ctx.createLinearGradient(0, 0, canvas.width, canvas.height);
    gradient.addColorStop(0, currentTheme.bgStart);
    gradient.addColorStop(1, currentTheme.bgEnd);
    ctx.fillStyle = gradient;
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    currentY = padding;
    ctx.fillStyle = currentTheme.textColor;

    ctx.font = `bold ${titleFontSize}px "Segoe UI", Roboto, sans-serif`;
    currentY = wrapText(ctx, title, padding, currentY + titleFontSize, width - padding * 2, lineHeightTitle);
    currentY += lineHeightContent * 0.5;

    ctx.font = `${contentFontSize}px "Segoe UI", Roboto, sans-serif`;
    for (const line of contentLines) {
         currentY = wrapText(ctx, line.trim(), padding, currentY, width - padding * 2, lineHeightContent);
    }


    return canvas.toBuffer('image/png');
}

async function makeNavyRequest(prompt, onChunk, imageUrls = null) {
  try {
    let messageContent;
    
    if (imageUrls && imageUrls.length > 0) {
      messageContent = [
        {
          type: "text",
          text: prompt
        }
      ];
      
      for (const imageUrl of imageUrls) {
        messageContent.push({
          type: "image_url",
          image_url: {
            url: imageUrl
          }
        });
      }
    } else {
      messageContent = prompt;
    }
    
    const response = await fetch('https://api.navy/v1/chat/completions', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer sk-admin-test-2000`
      },
      body: JSON.stringify({
        model: 'gpt-base',
        messages: [{
          role: "user",
          content: messageContent
        }],
        stream: true
      })
    });

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }

    let fullResponse = '';
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          const trimmedLine = line.trim();
          if (!trimmedLine) continue;
          
          if (trimmedLine.startsWith('data: ')) {
            const dataStr = trimmedLine.slice(6);
            
            if (dataStr === '[DONE]' || dataStr.includes('"type": "ping"')) {
              continue;
            }
            
            try {
              const data = JSON.parse(dataStr);
              const content = data.choices?.[0]?.delta?.content || '';
              
              if (content) {
                fullResponse += content;
                if (onChunk) onChunk(content);
              }
            } catch (parseError) {
              console.warn('Failed to parse streaming chunk from navy api, ignoring:', parseError.message);
              continue;
            }
          }
        }
      }
    } finally {
      reader.releaseLock();
    }
    
    if (!fullResponse) {
      return 'The AI service returned an empty response. Please try again.';
    }
    
    return fullResponse;
  } catch (error) {
    console.error('Navy API error:', error);
    
    if (error?.response?.status === 502) {
      return 'The AI service is currently unavailable. Please try again later.';
    }
    
    if (error?.message?.includes('invalid json') || error?.type === 'invalid-json') {
      return 'The AI service returned an invalid response. Please try again.';
    }
    
    return 'Sorry, there was an error processing your request.';
  }
}

async function renderStatsToImage(totalTokens, dailyTokens, theme = 'default', width = 800, height = 250) {
    const currentTheme = IMAGE_THEMES[theme] || IMAGE_THEMES.default;
    const canvas = createCanvas(width, height);
    const ctx = canvas.getContext('2d');

    const gradient = ctx.createLinearGradient(0, 0, canvas.width, canvas.height);
    gradient.addColorStop(0, currentTheme.bgStart);
    gradient.addColorStop(1, currentTheme.bgEnd);
    ctx.fillStyle = gradient;
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    ctx.fillStyle = currentTheme.textColor;
    ctx.font = 'bold 36px "Segoe UI", Roboto, sans-serif';
    ctx.textAlign = 'center';
    ctx.shadowColor = 'rgba(0, 0, 0, 0.4)';
    ctx.shadowBlur = 6;
    ctx.fillText('ExoML Usage Stats', canvas.width / 2, 60);
    ctx.shadowBlur = 0;

    const infoStartY = 120;
    const padding = 50;
    const labelMaxWidth = 350;
    const valueEndX = width - padding;
    const lineSpacing = 45;
    let currentY = infoStartY;

    function drawStatLine(label, value) {
        ctx.fillStyle = 'rgba(255, 255, 255, 0.8)';
        ctx.font = '20px "Segoe UI", Roboto, sans-serif';
        ctx.textAlign = 'left';
        ctx.fillText(label, padding, currentY, labelMaxWidth);

        ctx.fillStyle = currentTheme.textColor;
        ctx.font = 'bold 24px "Segoe UI", Roboto, sans-serif';
        ctx.textAlign = 'right';
        ctx.fillText(value, valueEndX, currentY);
        currentY += lineSpacing;
    }

    drawStatLine('Total Tokens Processed:', totalTokens.toLocaleString());
    drawStatLine("Today's Tokens (UTC):", dailyTokens.toLocaleString());

    ctx.fillStyle = 'rgba(255, 255, 255, 0.6)';
    ctx.font = '14px "Segoe UI", Roboto, sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText(`Last Updated: ${new Date().toLocaleString()}`, canvas.width / 2, canvas.height - 25);

    return canvas.toBuffer('image/png');
}
const trialKeyCooldowns = new Map();
const TRIAL_KEY_COOLDOWN_MS = 60 * 1000;

const models = {
  'gpt-4o-mini': { multiplier: 1 },
  'gpt-4o': { multiplier: 1 },
  'deepseek-chat': { multiplier: 1 },
  'command': { multiplier: 1 },
  'gemini-2.0-flash': { multiplier: 1 },
  'gemini-2.5-flash': { multiplier: 1 },
  'gemini-2.5-pro': { multiplier: 1 },
  'claude': { multiplier: 1 },
  'claude-thinking': { multiplier: 1 },
  'gpt-3.5-turbo': { multiplier: 1 },
  'gpt-4.1': { multiplier: 1 },
  'gpt-thinking': { multiplier: 1 },
  'chatgpt-4o-latest': { multiplier: 1 },
  'deepseek-r1': { multiplier: 1 },
  'gpt-search': { multiplier: 1 },
  'llama': { multiplier: 1 },
  'worm-r1': { multiplier: 1 },
  'gemma': { multiplier: 1 },
  'grok': { multiplier: 1 },
  'qwq-32b': { multiplier: 1 },
  'open-gemini-70b': { multiplier: 1 },
  'open-gemini-90b': { multiplier: 1 },
  'gpt-image-1': { multiplier: 1, type: 'image' },
  'flux': { multiplier: 1, type: 'image' },
  'dreamshaper': { multiplier: 1, type: 'image' },
  'proteus': { multiplier: 1, type: 'image' },
  'exo-image': { multiplier: 1, type: 'image' },
  'qwen-3-235b': { multiplier: 1 },
  'gpt-4.5-preview': { multiplier: 1 },
  'dalle': { multiplier: 1, type: 'image' },
  'r1-1776': { multiplier: 1 },
  'mistral-small': { multiplier: 1 },
  'mistral-large': { multiplier: 1 },
  'pixtral-large': { multiplier: 1 },
  'mistral-saba': { multiplier: 1 },
  'codestral': { multiplier: 1 },
  'codestral-mamba': { multiplier: 1 },
  'llama-4-scout': { multiplier: 1 },
  'llama-4-maverick': { multiplier: 1 },
  'dolphin': { multiplier: 1 },
  'runway': { multiplier: 1, type: 'video' },
  'flux.1-schnell': { multiplier: 1, type: 'image' },
  'flux.1-dev': { multiplier: 1, type: 'image' },
  'flux.1-pro': { multiplier: 1, type: 'image' },
  'flux.1.1-pro': { multiplier: 1, type: 'image' },
  'imagen-3': { multiplier: 1, type: 'image' },
  'imagen-3-5': { multiplier: 1, type: 'image' },
  'deepseek-r1-zero': { multiplier: 1 },
  'recraft': { multiplier: 1, type: 'image' },
  'secret': { multiplier: 1, type: 'image' },
  'html-agent': { multiplier: 1 },
  'claude-sonnet-4': { multiplier: 1 },
  'claude-3-7-sonnet': { multiplier: 1 },
  'claude-3-7-sonnet-thinking': { multiplier: 1 },
  'claude-sonnet-4-thinking': { multiplier: 1 },
  'claude-opus-4-thinking': { multiplier: 1 },
  'x-preview': { multiplier: 1 },
  'gpt-4o-alpha': { multiplier: 1 },
  'claude-opus-4': { multiplier: 1 },
  'flux.1-kontext-pro': { multiplier: 1, type: 'image'},
  'flux.1-kontext-max': { multiplier: 1, type: 'image'},
  'grok-3-beta': { multiplier: 1 },
  'mistral-medium-3': { multiplier: 1 },
  'codex-mini': { multiplier: 1 },
  'command-a': { multiplier: 1 },
  'sonar-reasoning-pro': { multiplier: 1 },
  'devstral-small': { multiplier: 1 },
  'gemini-2.5-flash-preview-05-20': { multiplier: 1 },
  'deepseek-r1-0528': { multiplier: 1 },
  'exo-gpt': { multiplier: 1 },
  'exo-no-gpt': { multiplier: 1 },
  'qwen2.5-coder': { multiplier: 1 },
  'qwen3-32b': { multiplier: 1 },
  'devstral': { multiplier: 1 },
  'mercury-coder-small': { multiplier: 1 },
  'o3': { multiplier: 1 },
  'o4-mini': { multiplier: 1 },
  'deepseek-140b': { multiplier: 1 },
  'fluffy': { multiplier: 1 },
  'claude-2': { multiplier: 1 },
  'llama3.3': { multiplier: 1 },
  'exo': { multiplier: 1 },
  'sora': { multiplier: 1, type: 'video'},
  'minimax-m1': { multiplier: 1},
  'marin-8b-instruct': { multiplier: 1},
  'ideogram': { multiplier: 1, type: 'image'},
  'realism': { multiplier: 1, type: 'image'},
  'uncensored': { multiplier: 1, type: 'image'},
  'afm-4.5b-preview': { multiplier: 1},
  'chatgpt-5': { multiplier: 1},
  'emotional': { multiplier: 1},
  'fast': { multiplier: 1},
  'codex-mini': { multiplier: 1, type: 'response'},
  'o3-pro': { multiplier: 1, type: 'response'},
  'o4-mini-deep-research': { multiplier: 1, type: 'response'},
  'anubis-70b': { multiplier: 1},
  'gemini-2.5-pro-exp-03-25': { multiplier: 1 },
  'claude-3-7-sonnet-20250219': { multiplier: 1 },
  'glm-z1-9b-0414': { multiplier: 1 },
  'flux.1-kontext-dev': { multiplier: 1, type: 'image'},
  'hermes3': { multiplier: 1 },
  'kimi-k2': { multiplier: 1 },
  'llama-3.3-nemotron-super-49b': { multiplier: 1 },
  'devstral-small-2505': { multiplier: 1 },
  'deepseek-v3-0324-selfhost': { multiplier: 1 },
  'kimi-k2-selfhost': { multiplier: 1 },
  'deepseek-r1t2-chimera': { multiplier: 1 },
  'llama-3.3-70b-fast': { multiplier: 1 },
  'qwen3-235b-a22b-2507': { multiplier: 1 },
  'exoml-search': { multiplier: 1 },
  'mario': { multiplier: 1 },
  'midjourney-v7': { multiplier: 1, type: 'image'},
  'midjourney-v6.1': { multiplier: 1, type: 'image'},
  'midjourney-v6': { multiplier: 1, type: 'image'},
  'midjourney-v5.1': { multiplier: 1, type: 'image'},
  'midjourney-v5.2': { multiplier: 1, type: 'image'},
  'midjourney-niji6': { multiplier: 1, type: 'image'},
  'midjourney': { multiplier: 1, type: 'image'},
  'bard': { multiplier: 1 },
  'flux.1-krea-dev': { multiplier: 1, type: 'image'},
  'compound-beta': { multiplier: 1 },
  'glm-4.5-air': { multiplier: 1 },
  'glm-4.5': { multiplier: 1 },
  'gpt-oss-120b': { multiplier: 1 },
  'gpt-oss-20b': { multiplier: 1 },
  'horizon-beta': { multiplier: 1 },
  'jupyter-base': { multiplier: 1 },
  'gpt-5': { multiplier: 1 },
  'gpt-5-mini': { multiplier: 1 },
  'gpt-5-nano': { multiplier: 1 },
  'gpt-5-chat': { multiplier: 1 },
  'exo-instant': { multiplier: 1 },
  'claude-opus-4-1-20250805': { multiplier: 1 },
  'tongyi-qianwen': { multiplier: 1 },
  'katelya-01': { multiplier: 1 },
  'qwen3-coder': { multiplier: 1 },
  'cogito-v2-llama-70b': { multiplier: 1 },
  'cogito-v2-llama-109b': { multiplier: 1 },
  'cogito-v2-llama-405b': { multiplier: 1 },
  'cogito-v2-deepseek-671b': { multiplier: 1 },
  'gpt-oss-120b-instant': { multiplier: 1 },
  'mistral-medium-latest': { multiplier: 1 },
};

const FLUX_IMAGE_CHANNEL_NAME = 'flux-image-generation';
const fluxImageCooldowns = new Map();
const FLUX_IMAGE_COOLDOWN_MS = 0 * 1000;
let size = "";

async function generateImage(prompt, modelName = "flux", imageUrl = null) {
    try {
        console.log(`[ImageGen] Requesting image with ${modelName} for prompt: "${prompt}"${imageUrl ? ` and image URL: ${imageUrl}` : ''}`);
        let size;
        if (modelName.includes("gpt") || modelName.includes("dalle") || modelName.includes("realism") || modelName.includes("imagen") || modelName.includes("uncensored")) {
            size = "1024x1024";
        } else {
            size = "512x512";
        }

        const requestBody = {
            model: modelName,
            prompt: prompt,
            n: 4,
            size: size,
            response_format: "url"
        };

        if (modelName === 'ideogram' || modelName === 'runway') {
            delete requestBody.n;
        }
        if (imageUrl) {
            if (modelName === "gpt-image-1") {
                requestBody.image_urls = [imageUrl];
            } else {
                requestBody.image_url = imageUrl;
            }
        }

        const fetch = (await import('node-fetch')).default;
        const response = await fetch('https://api.exomlapi.com/v1/images/generations', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${process.env.OPENAI_API_KEY || 'sk-2e4390ef9a39b127eddc152ea5380c601f0e84f924a3a1a5'}`
            },
            body: JSON.stringify(requestBody)
        });

        const responseData = await response.json();

        if (!response.ok) {
            throw {
                response: {
                    status: response.status,
                    data: responseData
                }
            };
        }

        if (responseData.data && responseData.data.length > 0) {
            const imageBuffers = [];
            for (const imageData of responseData.data) {
                if (imageData.url) {
                    const resultUrl = imageData.url;
                    console.log(`[ImageGen] Image URL received for model ${modelName}: ${resultUrl}`);
                    try {
                        const imageResponse = await fetch(resultUrl);
                        if (imageResponse.ok) {
                            const imageBuffer = await imageResponse.buffer();
                            imageBuffers.push({ buffer: imageBuffer, url: resultUrl });
                        } else {
                            console.error(`[ImageGen] Error downloading generated image from ${resultUrl}. Status: ${imageResponse.status}`);
                        }
                    } catch (fetchError) {
                        console.error(`[ImageGen] Error fetching image buffer for ${resultUrl}:`, fetchError);
                    }
                }
            }

            if (imageBuffers.length > 0) {
                return { success: true, images: imageBuffers };
            } else {
                return { success: false, error: 'Could not download any of the generated images.' };
            }
        } else {
            console.error('[ImageGen] Invalid response structure from API:', responseData);
            return { success: false, error: 'Invalid response structure from image generation API.' };
        }
    } catch (error) {
        console.error('[ImageGen] API error (images.generate):', JSON.stringify(error, null, 2));
        let errorMessage = 'Sorry, there was an error generating your image.';

        const apiError = error?.response?.data?.error || error?.error;

        if (apiError) {
            if (typeof apiError === 'string') {
                errorMessage = apiError;
            } else if (apiError.message) {
                errorMessage = apiError.message;
            } else {
                errorMessage = JSON.stringify(apiError);
            }
        } else if (error?.response?.status) {
            errorMessage += ` (Status: ${error.response.status})`;
        } else if (error.message) {
            errorMessage = error.message;
        }

        return { success: false, error: errorMessage };
    }
}

function sanitizeModelName(name) {
  if (name === 'gemini-20-flash') {
    return 'gemini-2.0-flash';
  }
  if (name === 'gemini-25-flash') {
    return 'gemini-2.5-flash';
  }
  if (name === 'gemini-25-pro') {
    return 'gemini-2.5-pro';
  }
  if (name === 'gpt-41') {
    return 'gpt-4.1';
  }
  if (name === 'gpt-35-turbo') {
    return 'gpt-3.5-turbo';
  }
  if (name === 'gpt-45-preview') {
    return 'gpt-4.5-preview';
  }
  if (name === 'flux1-schnell') {
    return 'flux.1-schnell';
  }
  if (name === 'flux1-dev') {
    return 'flux.1-dev';
  }
  if (name === 'flux1-pro') {
    return 'flux.1-pro';
  }
  if (name === 'flux11-pro') {
    return 'flux.1.1-pro';
  }
  if (name === 'flux1-kontext-pro') {
    return 'flux.1-kontext-pro';
  }
  if (name === 'flux1-kontext-max') {
    return 'flux.1-kontext-max';
  }
  if (name === 'flux1-kontext-dev') {
    return 'flux.1-kontext-dev';
  }
  if (name === 'gemini-25-flash-preview-05-20') {
    return 'gemini-2.5-flash-preview-05-20'
  }
  if (name === 'qwen25-coder') {
    return 'qwen2.5-coder'
  }
  if (name === 'sd-35') {
    return 'sd-3.5'
  }
  if (name === 'llama33') {
    return 'llama3.3'
  }

  if (name === 'afm-45b-preview') {
    return 'afm-4.5b-preview'
  }
  if (name === 'gemini-25-pro-exp-03-25') {
    return 'gemini-2.5-pro-exp-03-25'
  }
  if (name === 'llama-33-nemotron-super-49b') {
    return 'llama-3.3-nemotron-super-49b'
  }
  if (name === 'llama-33-70b-fast') {
    return 'llama-3.3-70b-fast'
  }
  if (name === 'midjourney-v61') {
    return 'midjourney-v6.1'
  }
  if (name === 'midjourney-v52') {
    return 'midjourney-v5.2'
  }
  if (name === 'midjourney-v51') {
    return 'midjourney-v5.1'
  }
  if (name === 'flux1-krea-dev') {
    return 'flux.1-krea-dev'
  }
  if (name === 'glm-45-air') {
    return 'glm-4.5-air'
  }
  if (name === 'glm-45') {
    return 'glm-4.5'
  }

  

  return name;
}


const client = new Client({
  intents: [
    GatewayIntentBits.Guilds,
    GatewayIntentBits.GuildMessages,
    GatewayIntentBits.MessageContent,
    GatewayIntentBits.GuildMembers
  ],
  allowedMentions: {
      parse: [],
      roles: [],
      users: [],
      repliedUser: false
  }
});

const commands = [
  {
    name: 'server',
    description: 'Get server information (Admin only)',
    default_member_permissions: String(PermissionsBitField.Flags.Administrator),
  },
  {
    name: 'ping',
    description: 'Responds with pong (Admin only)',
    default_member_permissions: String(PermissionsBitField.Flags.Administrator),
  },
  {
    name: 'ticket',
    description: 'Create a ticket panel (Admin only)',
    default_member_permissions: String(PermissionsBitField.Flags.Administrator)
  },
  {
    name: 'chat',
    description: 'Start an AI chat session (Admin only)',
    default_member_permissions: String(PermissionsBitField.Flags.Administrator),
    options: [
      {
        name: 'model',
        description: 'Choose the AI model to chat with',
        type: 3,
        required: false,
        choices: [
          {
            name: 'GPT-4 Mini',
            value: 'gpt-4o-mini'
          },
          {
            name: 'GPT-4o',
            value: 'gpt-4o'
          },
          {
            name: 'DeepSeek Chat',
            value: 'deepseek-chat'
          },
          {
            name: 'Gemini 2.0 Flash',
            value: 'gemini-2.0-flash'
          },
          {
            name: 'Grok-3',
            value: 'grok-3'
          },
          {
            name: 'Claude 3 Sonnet',
    value: 'claude-3-7-sonnet'
          },
          {
            name: 'Claude 3 Thinking',
            value: 'claude-3-7-sonnet-thinking'
          },
          {
            name: 'GPT-3.5 Turbo Instruct',
            value: 'gpt-3.5-turbo-instruct'
          },
          {
            name: 'GPT-4.1',
            value: 'gpt-4.1'
          }
        ]
      }
    ]
  },
  {
    name: 'setup',
    description: 'Manage bot setup and AI channel configuration',
    options: [
      {
        name: 'add_channel',
        description: 'Add a channel where the AI can respond',
        type: 1,
        options: [
          {
            name: 'channel',
            description: 'The channel to allow the AI in',
            type: 7,
            required: true,
            channel_types: [0]
          }
        ]
      },
      {
        name: 'remove_channel',
        description: 'Remove a channel where the AI can respond',
        type: 1,
        options: [
          {
            name: 'channel',
            description: 'The channel to disallow the AI in',
            type: 7,
            required: true,
            channel_types: [0]
          }
        ]
      },
      {
        name: 'list_channels',
        description: 'List the channels where the AI is currently allowed to respond',
        type: 1
      },
      {
          name: 'create_defaults',
          description: 'Create the default set of dedicated AI model channels',
          type: 1
      }
    ],
    default_member_permissions: String(PermissionsBitField.Flags.Administrator)
  },
  {
    name: 'setupall',
    description: 'Set up/reset standard channels, categories, rename server (Admin only)',
    default_member_permissions: String(PermissionsBitField.Flags.Administrator),
    options: [
      {
        name: 'server_name',
        description: 'The name to use for the server and in announcements',
        type: 3,
        required: true
      },
      {
        name: 'theme',
        description: 'Select a color theme for announcement/rules images (optional, saves choice)',
        type: 3,
        required: false,
        choices: Object.keys(IMAGE_THEMES).map(themeName => ({ name: themeName, value: themeName }))
      }
    ]
  },
  {
    name: 'adduser',
    description: 'Add a new API key for a user (Admin only)',
    default_member_permissions: String(PermissionsBitField.Flags.Administrator),
    options: [
      {
        name: 'user',
        description: 'The user to add the key for',
        type: 6,
        required: true
      },
      {
        name: 'api_key',
        description: 'The new API key to add (e.g., sk-...)',
        type: 3,
        required: true
      },
      {
        name: 'plan',
        description: 'The usage plan for the key (default: 0)',
        type: 3,
        required: false,
        choices: [
            { name: '0 Tokens (Disabled effectively)', value: '0' },
            { name: '500k Tokens/Day', value: '500k' },
            { name: '100m Tokens/Day', value: '100m' },
            { name: 'Unlimited Tokens/Day', value: 'unlimited' },
            { name: 'Pay2Go (Prepaid Tokens)', value: 'pay2go' }
        ]
      }
    ]
  },
  {
    name: 'enableuser',
    description: 'Enable an existing API key (Admin only)',
    default_member_permissions: String(PermissionsBitField.Flags.Administrator),
    options: [
        {
            name: 'user',
            description: 'The user whose API key to enable',
            type: 6,
            required: true
        }
    ]
  },
  {
    name: 'disableuser',
    description: 'Disable an existing API key (Admin only)',
    default_member_permissions: String(PermissionsBitField.Flags.Administrator),
    options: [
        {
            name: 'user',
            description: 'The user whose API key to disable',
            type: 6,
            required: true
        }
    ]
  },
  {
    name: 'changeplan',
    description: 'Change the usage plan for an existing API key (Admin only)',
    default_member_permissions: String(PermissionsBitField.Flags.Administrator),
    options: [
        {
            name: 'user',
            description: 'The user whose API key plan to change',
            type: 6,
            required: true
        },
        {
            name: 'new_plan',
            description: 'The new usage plan for the key',
            type: 3,
            required: true,
            choices: [
                { name: '0 Tokens (Disabled effectively)', value: '0' },
                { name: '500k Tokens/Day', value: '500k' },
                { name: '100m Tokens/Day', value: '100m' },
                { name: 'Unlimited Tokens/Day', value: 'unlimited' },
                { name: 'Pay2Go (Prepaid Tokens)', value: 'pay2go' }
            ]
        }
    ]
  },
  {
    name: 'viewkeys',
    description: 'View all API keys and user information (Admin only)',
    default_member_permissions: String(PermissionsBitField.Flags.Administrator),
  },
  {
    name: 'viewkey',
    description: 'View the API key details for a specific user (Admin only)',
    default_member_permissions: String(PermissionsBitField.Flags.Administrator),
    options: [
        {
            name: 'user',
            description: 'The user whose API key to view',
            type: 6,
            required: true
        }
    ]
  },
  {
      name: 'resetkey',
      description: 'Reset the API key for a user to a new random value (Admin only)',
      default_member_permissions: String(PermissionsBitField.Flags.Administrator),
      options: [
          {
              name: 'user',
              description: 'The user whose API key to reset',
              type: 6,
              required: true
          }
      ]
  },
  {
      name: 'addtokens',
      description: 'Add tokens to a pay2go user (Admin only)',
      default_member_permissions: String(PermissionsBitField.Flags.Administrator),
      options: [
          {
              name: 'user',
              description: 'The user to add tokens to',
              type: 6,
              required: true
          },
          {
              name: 'tokens',
              description: 'Number of tokens to add',
              type: 4,
              required: true
          }
      ]
  },
  {
      name: 'upgradepay2go',
      description: 'Upgrade/downgrade a pay2go user for premium model access (Admin only)',
      default_member_permissions: String(PermissionsBitField.Flags.Administrator),
      options: [
          {
              name: 'user',
              description: 'The user to upgrade/downgrade',
              type: 6,
              required: true
          },
          {
              name: 'upgraded',
              description: 'Whether to grant premium access',
              type: 5,
              required: true
          }
      ]
  },
  {
    name: 'allow_opensource',
    description: 'Enable or disable opensource model access for a user (Admin only)',
    default_member_permissions: String(PermissionsBitField.Flags.Administrator),
    options: [
      {
        name: 'user',
        description: 'The user to modify opensource access for',
        type: 6,
        required: true
      },
      {
        name: 'enabled',
        description: 'Whether to enable or disable opensource access',
        type: 5,
        required: true
      },
      {
        name: 'rpm_limit',
        description: 'Requests per minute limit for opensource models (default: 60)',
        type: 4,
        required: false,
        min_value: 1,
        max_value: 300
      }
    ]
  }
];

async function callAdminApi(action, payload) {
    const adminKey = process.env.ADMIN_API_KEY;
    if (!adminKey) {
        return { success: false, data: { error: "Admin API Key is not configured in the bot's environment." } };
    }

    const apiUrl = 'https://api.exomlapi.com/admin/keys';

    try {
        const response = await fetch(apiUrl, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${adminKey}`
            },
            body: JSON.stringify({ action, ...payload })
        });

        const responseData = await response.json();

        if (response.ok) {
            return { success: true, data: responseData };
        } else {
            console.error(`Admin API Error (${response.status}):`, responseData);
            return { success: false, data: responseData || { error: `HTTP Error ${response.status}` } };
        }
    } catch (error) {
        console.error('Error calling Admin API:', error);
        return { success: false, data: { error: `Network or fetch error: ${error.message}` } };
    }
}

async function callAdminApiGet(path = '/admin/keys') {
    const adminKey = process.env.ADMIN_API_KEY;
    if (!adminKey) {
        return { success: false, data: { error: "Admin API Key is not configured in the bot's environment." } };
    }

    const apiUrl = `https://api.exomlapi.com${path}`;

    try {
        const response = await fetch(apiUrl, {
            method: 'GET',
            headers: {
                'Authorization': `Bearer ${adminKey}`,
                'Accept': 'application/json'
            }
        });

        const responseData = await response.json();

        if (response.ok) {
            return { success: true, data: responseData };
        } else {
            console.error(`Admin GET API Error (${response.status}) on path ${path}:`, responseData);
            return { success: false, data: responseData || { error: `HTTP Error ${response.status}` } };
        }
    } catch (error) {
        console.error(`Error calling Admin GET API on path ${path}:`, error);
        return { success: false, data: { error: `Network or fetch error: ${error.message}` } };
    }
}

async function getChatModelNamesFromAPI() {
    console.log("[ModelsAPI] Fetching available models from https://api.exomlapi.com/v1/models");
    try {
        const response = await fetch('https://api.exomlapi.com/v1/models');
        if (!response.ok) {
            console.error(`[ModelsAPI] Error fetching models: ${response.status} ${response.statusText}`);
            const errorBody = await response.text();
            console.error(`[ModelsAPI] Error body: ${errorBody}`);
            return [];
        }
        const responseData = await response.json();

        if (!responseData || !responseData.data || !Array.isArray(responseData.data)) {
            console.error('[ModelsAPI] Invalid or unexpected format from models API:', responseData);
            return [];
        }

        const chatModelNames = [];
        for (const modelApiEntry of responseData.data) {
            const modelId = modelApiEntry.id;
            if (!modelId) {
                continue;
            }

            const localModelConfig = models[modelId];
            if (localModelConfig && (localModelConfig.type === 'image' || localModelConfig.type === 'video')) {
                continue;
            }
            chatModelNames.push(modelId);
        }
        console.log(`[ModelsAPI] Found ${chatModelNames.length} chat models from API to create channels for.`);
        return chatModelNames;

    } catch (error) {
        console.error('[ModelsAPI] Failed to fetch or parse models:', error);
        return [];
    }
}

client.on('ready', async () => {
  console.log(`Logged in as ${client.user.tag}!`);
  
  const rest = new REST({ version: '10' }).setToken(process.env.TOKEN);

  try {
    await rest.put(
      Routes.applicationCommands(client.user.id),
      { body: commands }
    );
    console.log('Successfully registered application commands.');
  } catch (error) {
    console.error(error);
  }
});

client.on('ready', async () => {
  console.log(`Logged in as ${client.user.tag}!`);

  const roleId = '1380349348587507794';

  for (const [guildId, guild] of client.guilds.cache) {
    if (guildId === '1398368324286550107') continue;
    console.log(`Checking members for role in guild: ${guild.name} (${guildId})`);
    const role = guild.roles.cache.get(roleId);

    if (!role) {
      console.warn(`Role with ID ${roleId} not found in guild ${guild.name}. Skipping role assignment for this guild.`);
      continue;
    }

    try {
      const members = await guild.members.fetch();
      for (const [memberId, member] of members) {
        if (!member.user.bot && !member.roles.cache.has(roleId)) {
          try {
            await member.roles.add(role);
            console.log(`Assigned member role to existing user ${member.user.tag} in guild ${guild.name}`);
          } catch (error) {
            console.error(`Failed to assign member role to existing user ${member.user.tag} in guild ${guild.name}:`, error);
          }
        }
      }
    } catch (fetchError) {
      console.error(`Failed to fetch members for guild ${guild.name}:`, fetchError);
    }
  }

  console.log(`Logged in as ${client.user.tag}!`);
  console.log(`Logged in as ${client.user.tag}!`);

  const ensureApiInfoChannel = async (guild) => {
    const categoryName = '👋 WELCOME & INFO';
    const channelName = 'api-info-docs';
    let category = guild.channels.cache.find(c => c.name === categoryName && c.type === 4);
    if (!category) {
        try {
            category = await guild.channels.create({ name: categoryName, type: 4 });
            console.log(`Created category: ${category.name}`);
        } catch (error) {
            console.error(`Failed to create category '${categoryName}':`, error);
            return;
        }
    }

    let channel = guild.channels.cache.find(c => c.name === channelName && c.parentId === category.id);
    if (!channel) {
        try {
            channel = await guild.channels.create({
                name: channelName,
                type: 0,
                topic: 'API documentation and information.',
                parent: category.id,
            });
            console.log(`Created channel #${channel.name} in category ${category.name}`);
        } catch (error) {
            console.error(`Failed to create channel #${channelName}:`, error);
            return;
        }
    }

    try {
        const messages = await channel.messages.fetch({ limit: 1 });
        const lastMessage = messages.first();
        if (!lastMessage || lastMessage.author.id !== client.user.id) {
            await fetch(`https://discord.com/api/v10/channels/${channel.id}/messages`, {
                method: 'POST',
                headers: {
                    'Authorization': `Bot ${process.env.TOKEN}`,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(apiInfoPayload)
            });
            console.log(`Posted/updated API info panel to #${channel.name}`);
        } else {
            console.log(`API info panel already exists in #${channel.name}`);
        }
    } catch (error) {
        console.error(`Failed to check messages or post panel in #${channelName}:`, error);
    }
  };

  for (const [guildId, guild] of client.guilds.cache) {
      if (guildId === '1398368324286550107') continue;
      await ensureApiInfoChannel(guild);
  }
  
  const findOrCreateChannel = async (guild, channelName) => {
    let channel = guild.channels.cache.find(c => c.name === channelName && c.type === 0);
    if (!channel) {
      try {
        channel = await guild.channels.create({
          name: channelName,
          type: 0,
          topic: 'Bot statistics and usage information.',
          permissionOverwrites: [
            {
              id: guild.roles.everyone,
              deny: ['SendMessages'],
              allow: ['ViewChannel']
            },
            {
              id: client.user.id,
              allow: ['SendMessages', 'EmbedLinks']
            }
          ]
        });
        console.log(`Created channel #${channelName}`);
      } catch (error) {
        console.error(`Failed to create channel #${channelName}:`, error);
        return null;
      }
    }
    return channel;
  };

  const updateStatsImage = async () => {
    let usageData;
    try {
        const response = await fetch('https://api.exomlapi.com/v1/usage', {
            method: 'GET',
            headers: {
                'Authorization': 'Bearer sl-asdjfkawelrjioewqrioqwejiorewqi'
            }
        });

        if (!response.ok) {
            console.error(`Error fetching usage stats: ${response.status} ${response.statusText}`);
            return;
        }
        usageData = await response.json();
    } catch (fetchError) {
        console.error('Network or fetch error getting usage stats:', fetchError);
        return;
    }

    let imageBuffer;
    try {
        const currentConfig = readConfig();
        imageBuffer = await renderStatsToImage(
            usageData.total_tokens_processed || 0,
            usageData.daily_tokens_processed_today_utc || 0,
            currentConfig.theme
        );
    } catch (renderError) {
        console.error('Error rendering stats image:', renderError);
        return;
    }

    for (const [guildId, guild] of client.guilds.cache) {
        if (guildId === '1398368324286550107') {
            console.log(`Skipping stats update for excluded guild: ${guild.name} (${guildId})`);
            continue;
        }
        console.log(`Processing stats update for guild: ${guild.name} (${guildId})`);
        try {
            const statsChannel = await findOrCreateChannel(guild, 'stats');
            if (!statsChannel) {
                console.error(`Could not find or create the stats channel in guild ${guild.name}. Skipping.`);
                continue;
            }

            const messages = await statsChannel.messages.fetch({ limit: 1 });
            const lastMessage = messages.first();

            if (lastMessage && lastMessage.author.id === client.user.id && lastMessage.attachments.size > 0) {
                try {
                    await lastMessage.edit({
                        files: [{ attachment: imageBuffer, name: 'stats.png' }],
                        embeds: []
                    });
                        console.log(`Edited stats message in #${statsChannel.name} for guild ${guild.name}`);
                } catch (editError) {
                    console.error(`Failed to edit existing stats message in #${statsChannel.name} for guild ${guild.name}, sending new one:`, editError);
                    await statsChannel.send({ files: [{ attachment: imageBuffer, name: 'stats.png' }] });
                }
            } else {
                    try {
                    const botMessages = (await statsChannel.messages.fetch({ limit: 10 })).filter(m => m.author.id === client.user.id && m.id !== lastMessage?.id);
                    if (botMessages.size > 0) {
                        await statsChannel.bulkDelete(botMessages);
                        console.log(`Bulk deleted ${botMessages.size} old bot messages in #${statsChannel.name} for guild ${guild.name}`);
                    }
                    } catch (deleteError) {
                        console.error(`Couldn't bulk delete old messages in #${statsChannel.name} for guild ${guild.name}:`, deleteError);
                    }
                await statsChannel.send({ files: [{ attachment: imageBuffer, name: 'stats.png' }] });
                    console.log(`Sent new stats message to #${statsChannel.name} for guild ${guild.name}`);
            }
        } catch (guildError) {
            console.error(`Error processing stats update for guild ${guild.name} (${guildId}):`, guildError);
        }
    }
  };

  updateStatsImage();

  setInterval(updateStatsImage, 60000);
const trialChannelId = '1381753170602233897';
const trialMessageId = '1381753172481146941';

const trialChannel = client.channels.cache.get(trialChannelId);
if (trialChannel && trialChannel.guild.id !== '1398368324286550107') {
  try {
    const trialMessage = await trialChannel.messages.fetch(trialMessageId);
    if (trialMessage) {
      const updatedTrialEmbed = {
        title: '🚀 Free Trial API Key',
        description: 'Click the button below to receive your **free API key** with a **500,000 token/day limit**!\n\nIf you already have a key (trial or otherwise), clicking the button will simply display your existing key.\n\nBy pressing the button, you agree to our [Privacy Policy](https://api.exomlapi.com/privacy) and [Terms of Service](https://api.exomlapi.com/terms).',
        color: 0x2ECC71,
        footer: { text: 'Enjoy your free access!' }
      };

      const updatedTrialRow = new ActionRowBuilder()
        .addComponents(
          new ButtonBuilder()
            .setCustomId('get_trial_key')
            .setLabel('Get/View My Trial Key')
            .setStyle(ButtonStyle.Success)
            .setEmoji('🔑')
        );

      await trialMessage.edit({ embeds: [updatedTrialEmbed], components: [updatedTrialRow] });
      console.log('Free trial embed updated successfully.');
    }
  } catch (error) {
    console.error('Error updating free trial embed:', error);
  }
}
});

client.on('guildCreate', async guild => {
  const channel = await guild.channels.create({
    name: 'tickets',
    type: 0,
    topic: 'Create a ticket here for support',
    permissionOverwrites: [
      {
        id: guild.id,
        deny: ['SendMessages'],
        allow: ['ViewChannel']
      }
    ]
  });

  const embed = {
    title: 'Support Tickets',
    description: 'Click the button below to create a private support ticket',
    color: 0x5865F2,
    thumbnail: {
      url: 'https://discord.com/assets/1c8a54f25d101ecdfe6d0c52416f8f0a.svg'
    },
    fields: [
      {
        name: 'Privacy',
        value: 'All tickets are private and only visible to you and staff',
        inline: true
      },
      {
        name: 'Response Time',
        value: 'We aim to respond within 24 hours',
        inline: true
      }
    ],
    footer: {
      text: 'Need help? Contact server admins'
    }
  };

  const row = new ActionRowBuilder()
    .addComponents(
      new ButtonBuilder()
        .setCustomId('create_ticket')
        .setLabel('Create Ticket')
        .setStyle(ButtonStyle.Primary)
    );

  await channel.send({ embeds: [embed], components: [row] });
});

client.on('interactionCreate', async interaction => {
  if (!interaction.isButton() || interaction.customId !== 'create_ticket') return;

  const thread = await interaction.channel.threads.create({
    name: `ticket-${interaction.user.username}`,
    autoArchiveDuration: 1440,
    reason: `Support ticket for ${interaction.user.username}`,
    type: 12,
    invitable: false,
    permissionOverwrites: [
      {
        id: interaction.guild.id,
        deny: ['ViewChannel']
      },
      {
        id: interaction.user.id,
        allow: ['ViewChannel', 'SendMessages', 'ReadMessageHistory']
      }
    ]
  });

  await thread.members.add(interaction.user.id);
  await interaction.reply({ 
    content: `Ticket created: ${thread}`, 
    ephemeral: true 
  });

  const welcomeEmbed = {
    title: 'Support Ticket',
    description: `Hello ${interaction.user}, a staff member will assist you shortly.\n\nPlease describe your issue in detail.`,
    color: 0x5865F2
  };

  const closeButton = new ActionRowBuilder()
    .addComponents(
      new ButtonBuilder()
        .setCustomId('close_ticket')
        .setLabel('Close Ticket')
        .setStyle(ButtonStyle.Danger)
    );

  await thread.send({ 
    embeds: [welcomeEmbed],
    components: [closeButton] 
  });
  
});


const docs_content = {
    "chat_completions": {
        "title": "💬 Chat Completions API",
        "description": "Generate responses for conversational interactions.",
        "url": "https://api.exomlapi.com/docs#chat",
        "code": {
            "python": "```python\nfrom openai import OpenAI\n\nclient = OpenAI(\n    api_key=\"YOUR_API_KEY\",\n    base_url=\"https://api.exomlapi.com/v1\"\n)\n\nresponse = client.chat.completions.create(\n    model=\"gpt-3.5-turbo\",\n    messages=[{\"role\": \"user\", \"content\": \"Hello!\"}]\n)\nprint(response.choices[0].message.content)\n```",
            "curl": "```bash\ncurl -X POST \"https://api.exomlapi.com/v1/chat/completions\" \\\n  -H \"Content-Type: application/json\" \\\n  -H \"Authorization: Bearer YOUR_API_KEY\" \\\n  -d '{\n    \"model\": \"gpt-3.5-turbo\",\n    \"messages\": [\n      {\"role\": \"user\", \"content\": \"Hello!\"}\n    ]\n  }'\n```"
        }
    },
    "image_generation": {
        "title": "🖼️ Image Generation API",
        "description": "Create unique images from textual descriptions.",
        "url": "https://api.exomlapi.com/docs#images",
        "code": {
            "python": "```python\nfrom openai import OpenAI\n\nclient = OpenAI(\n    api_key=\"YOUR_API_KEY\",\n    base_url=\"https://api.exomlapi.com/v1\"\n)\n\nresponse = client.images.generate(\n    prompt=\"A cute baby sea otter\",\n    n=1,\n    size=\"1024x1024\"\n)\nprint(response.data[0].url)\n```"
        }
    },
    "embeddings": {
        "title": "🧠 Embeddings API",
        "description": "Convert text into numerical representations for semantic search.",
        "url": "https://api.exomlapi.com/docs#embeddings",
        "code": {
            "python": "```python\nfrom openai import OpenAI\n\nclient = OpenAI(\n    api_key=\"YOUR_API_KEY\",\n    base_url=\"https://api.exomlapi.com/v1\"\n)\n\nresponse = client.embeddings.create(\n    model=\"text-embedding-ada-002\",\n    input=\"The quick brown fox jumps over the lazy dog\"\n)\nprint(response.data[0].embedding)\n```"
        }
    }
};

const apiInfoPayload = {
   "flags": 1 << 15,
   "components": [
       {
           "type": 17,
           "accent_color": 0x22c55e,
           "components": [
               {
                   "type": 9,
                   "components": [
                       { "type": 10, "content": "# exomlapi.com | Unlimited AI Tokens" },
                       { "type": 10, "content": "Access up to 1B+ AI tokens daily with lifetime plans. Multiple payment options, no rate limits, and fully OpenAI-compatible." }
                   ],
                   "accessory": {
                       "type": 11,
                       "media": { "url": "https://api.exomlapi.com/favicon.png" },
                       "description": "exomlapi.com Logo"
                   }
               },
               { "type": 14, "divider": true, "spacing": 1 },
               { "type": 10, "content": "### ✨ Key Features" },
               { "type": 10, "content": "- **1B+ Tokens Daily**: No rate limits to stop your creativity.\n- **Lifetime Access**: Pay once, use forever.\n- **OpenAI Compatible**: Drop-in replacement for your existing code." },
               { "type": 14 },
               {
                   "type": 1,
                   "components": [
                       { "type": 2, "label": "Get Started", "style": 5, "url": "https://api.exomlapi.com" },
                       { "type": 2, "label": "Join Discord", "style": 5, "url": "https://discord.gg/exoml" },
                       { "type": 2, "label": "View Pricing", "style": 2, "custom_id": "view_pricing" }
                   ]
               },
               {
                   "type": 1,
                   "components": [
                       {
                           "type": 3,
                           "custom_id": "docs_select_menu",
                           "placeholder": "📚 Explore the Docs",
                           "options": [
                               { "label": "Chat Completions", "value": "chat_completions", "description": "/v1/chat/completions", "emoji": {"name": "💬"} },
                               { "label": "Image Generation", "value": "image_generation", "description": "/v1/images/generations", "emoji": {"name": "🖼️"} },
                               { "label": "Embeddings", "value": "embeddings", "description": "/v1/embeddings", "emoji": {"name": "🧠"} }
                           ]
                       }
                   ]
               },
               {
                   "type": 12,
                   "items": [
                       { "media": {"url": "https://anondrop.net/1394845051514917016/coollogo_com-22931223.png"}, "description": "Exomlapi Banner" }
                   ]
               }
           ]
       }
   ]
};

function splitMessage(text, maxLength) {
    const sentences = text.split('\n');
    const chunks = [];
    let currentChunk = '';

    for (const sentence of sentences) {
        if (currentChunk.length + sentence.length + 1 <= maxLength) {
            currentChunk += sentence + '\n';
        } else {
            if (currentChunk.length > 0) {
                chunks.push(currentChunk);
            }
            currentChunk = sentence + '\n';
        }
    }

    if (currentChunk.length > 0) {
        chunks.push(currentChunk);
    }

    const finalChunks = [];
    for (const chunk of chunks) {
        if (chunk.length > maxLength) {
            for (let i = 0; i < chunk.length; i += maxLength) {
                finalChunks.push(chunk.substring(i, i + maxLength));
            }
        } else {
            finalChunks.push(chunk);
        }
    }

    return finalChunks;
}

client.on('messageCreate', async message => {
    if (message.author.bot) return;

    if (message.channel.type === 1 && models[message.content.split(' ')[0]]) {
        const guild = client.guilds.cache.first();
        if (guild) {
            const owner = await guild.fetchOwner();
            await owner.send(`API DM from ${message.author.tag}: ${message.content}`);
        }
        return;
    }

    if ([0, 11].includes(message.channel.type)) {
        const channels = message.guild.channels.cache.filter(c =>
            c.type === message.channel.type && c.name === message.channel.name && c.id !== message.channel.id
        );
        channels.forEach(c => c.delete().catch(console.error));
    }

    const rawChannelName = message.channel.name;
    const normalizedChannelName = normalizeChannelName(rawChannelName);
    const sanitizedChannelName = sanitizeModelName(rawChannelName);

    const config = readConfig();
    const isAllowedChannel = config.allowedChannels?.includes(normalizedChannelName);
    const isChatThread = message.channel.isThread() && rawChannelName.startsWith('chat-');
    const isModelChannel = models[sanitizedChannelName] && models[sanitizedChannelName].type !== 'image' && models[sanitizedChannelName].type !== 'video';
    const isSpecificChannelId = message.channel.id === '1367675807736135790';
    const isUncensoredChannelId = message.channel.id === '1396896604048462006';
    const isFluxImageChannel = rawChannelName === FLUX_IMAGE_CHANNEL_NAME;
    const isGenericImageModelChannel = models[sanitizedChannelName] && (models[sanitizedChannelName].type === 'image' || models[sanitizedChannelName].type === 'video');

    if (isFluxImageChannel || isGenericImageModelChannel) {
        console.log(`[${new Date().toISOString()}] Processing image generation request ID ${message.id} in channel ${message.channel.name} (Type: ${isFluxImageChannel ? 'DedicatedFlux' : 'GenericImageModel'}) by user ${message.author.id}`);
        const userId = message.author.id;
        const now = Date.now();
        const lastRequestTime = fluxImageCooldowns.get(userId);

        if (lastRequestTime && (now - lastRequestTime < FLUX_IMAGE_COOLDOWN_MS)) {
            const timeLeft = Math.ceil((FLUX_IMAGE_COOLDOWN_MS - (now - lastRequestTime)) / 1000);
            await message.reply({
                content: `⏳ Please wait ${timeLeft} more seconds before generating another image.`,

            });
            console.log(`[ImageGenCooldown] User ${userId} tried too soon. ${timeLeft}s remaining.`);
            return;
        }

        try {
            await message.channel.sendTyping();
            const prompt = message.content;
            if (!prompt.trim()) {
                await message.reply({ content: "Please provide a prompt for image generation." });
                return;
            }

            fluxImageCooldowns.set(userId, now);

            let imageModelToUse;
            if (isFluxImageChannel) {
                imageModelToUse = "flux";
            } else {
                imageModelToUse = sanitizedChannelName;
            }

            let imageUrl = null;
            if (message.attachments.size > 0) {
                const attachment = message.attachments.first();
                if (attachment && attachment.contentType && attachment.contentType.startsWith('image/')) {
                    imageUrl = attachment.url;
                    console.log(`[ImageGen] Found uploaded image: ${imageUrl}`);
                }
            }

            const imageResult = await generateImage(prompt, imageModelToUse, imageUrl);

            if (imageResult.success && imageResult.images && imageResult.images.length > 0) {
                const files = imageResult.images.map((img, index) => ({
                    attachment: img.buffer,
                    name: `generated-image-${index + 1}.png`
                }));

                const chunks = [];
                for (let i = 0; i < files.length; i += 10) {
                    chunks.push(files.slice(i, i + 10));
                }

                for (let i = 0; i < chunks.length; i++) {
                    const chunk = chunks[i];
                    const isFirstMessage = i === 0;
                    
                    await message.reply({
                        files: chunk,
                        content: isFirstMessage ? `Images generated with ${imageModelToUse}:\n\n**Prompt:** ${prompt.substring(0, 1800)}` : undefined,
                    });
                }

                console.log(`[${new Date().toISOString()}] Replied to image request ID ${message.id} for model ${imageModelToUse} with ${imageResult.images.length} image(s).`);
            } else {
                const mediaType = models[imageModelToUse]?.type === 'video' ? 'video' : 'image';
                await message.reply({ content: `Sorry, could not generate the ${mediaType} with ${imageModelToUse}. ${imageResult.error || 'An unknown error occurred.'}` });
                console.warn(`[${new Date().toISOString()}] Failed ${mediaType} generation for ID ${message.id}. Error: ${imageResult.error}`);
            }
        } catch (error) {
            const mediaType = models[imageModelToUse]?.type === 'video' ? 'video' : 'image';
            console.error(`[${new Date().toISOString()}] Error processing ${mediaType} generation message ID ${message.id}:`, error);
            await message.reply({ content: `Sorry, there was an unexpected error generating your ${mediaType}.` });
        }
    } else if (isUncensoredChannelId || isChatThread || isModelChannel || isSpecificChannelId || isAllowedChannel) {
        console.log(`[${new Date().toISOString()}] Processing message ID ${message.id} in channel ${message.channel.name} (${message.channel.id})`);
        try {
            await message.channel.sendTyping();

            let model;
            if (isChatThread) {
                let derivedModel = rawChannelName.split('-').pop();
                model = sanitizeModelName(derivedModel);
            } else if (isModelChannel) {
                model = sanitizedChannelName;
            } else if (isSpecificChannelId) {
                model = 'gemini-2.0-flash';
            } else {
                let potentialModel = sanitizeModelName(normalizedChannelName);
                model = models[potentialModel] && models[potentialModel].type !== 'image' && models[potentialModel].type !== 'video' ? potentialModel : 'gpt-4o-mini';
                console.log(`Responding in allowed channel '${normalizedChannelName}', potential model '${potentialModel}', using model '${model}'`);
            }


            if (!models[model] || models[model].type === 'image' || models[model].type === 'video') {
                console.warn(`Attempted to use invalid, image, or video model '${model}' for chat. Defaulting to gpt-4o-mini.`);
                model = 'gpt-4o-mini';
            }


            let imageUrls = [];
            if (message.attachments.size > 0) {
                for (const attachment of message.attachments.values()) {
                    if (attachment.contentType && attachment.contentType.startsWith('image/')) {
                        imageUrls.push(attachment.url);
                        console.log(`[Chat] Found image attachment: ${attachment.url}`);
                    }
                }
            }

            let responseContent = '';
            console.log(`[${new Date().toISOString()}] Calling ExoML API for message ID ${message.id} with model ${model}${imageUrls.length > 0 ? ` and ${imageUrls.length} image(s)` : ''}`);
            
            let aiResponse;
            if (isUncensoredChannelId) {
                console.log(`[${new Date().toISOString()}] Using Navy API for uncensored channel`);
                aiResponse = await makeNavyRequest(message.content, (chunk) => {
                    responseContent += chunk;
                }, imageUrls.length > 0 ? imageUrls : null);
            } else if (models[model] && models[model].type === 'response') {
                console.log(`[${new Date().toISOString()}] Using v1/responses endpoint for model ${model}`);
                aiResponse = await makeExoMLResponseRequest(message.content, model, (chunk) => {
                    responseContent += chunk;
                }, imageUrls.length > 0 ? imageUrls : null);
            } else {
                aiResponse = await makeExoMLRequest(message.content, model, (chunk) => {
                    responseContent += chunk;
                }, imageUrls.length > 0 ? imageUrls : null);
            }
            
            console.log(`[${new Date().toISOString()}] Received API response for message ID ${message.id}. Length: ${aiResponse?.length || 0}`);

            let finalResponse = aiResponse;
            if (imageUrls.length > 0) {
                const imageCount = imageUrls.length;
                const imageText = imageCount === 1 ? 'image' : 'images';
                console.log(`[Chat] Processed ${imageCount} ${imageText} with text prompt for model ${model}`);
            }

            

            const MAX_LENGTH = 2000;
            const TRUNCATION_INDICATOR = "\n\n[...] (Response truncated due to length)";
            
            const sanitizedAiResponse = removeEveryoneHereMentions(finalResponse);

            if (sanitizedAiResponse && sanitizedAiResponse.length > MAX_LENGTH) {
        const messageChunks = splitMessage(sanitizedAiResponse, MAX_LENGTH);
        let currentPage = 0;

        const buttonRow = new ActionRowBuilder()
            .addComponents(
                new ButtonBuilder()
                    .setCustomId('previous')
                    .setLabel('Previous')
                    .setStyle(ButtonStyle.Primary)
                    .setDisabled(true),
                new ButtonBuilder()
                    .setCustomId('next')
                    .setLabel('Next')
                    .setStyle(ButtonStyle.Primary)
                    .setDisabled(messageChunks.length === 1)
            );

        await message.reply({
            content: removeEveryoneHereMentions(messageChunks[currentPage]),
            components: [buttonRow]
        });

        const filter = i => i.customId === 'previous' || i.customId === 'next';
        const collector = message.channel.createMessageComponentCollector({ filter, time: 60000 });

        collector.on('collect', async i => {
            if (i.user.id !== message.author.id) {
                return i.reply({ content: 'These buttons are not for you!', ephemeral: true });
            }

            if (i.customId === 'previous' && currentPage > 0) {
                currentPage--;
            } else if (i.customId === 'next' && currentPage < messageChunks.length - 1) {
                currentPage++;
            }

            buttonRow.components[0].setDisabled(currentPage === 0);
            buttonRow.components[1].setDisabled(currentPage === messageChunks.length - 1);

            await i.update({
                content: messageChunks[currentPage],
                components: [buttonRow],

            });
        });

        collector.on('end', collected => {
            if (collected.size === 0) {
                buttonRow.components[0].setDisabled(true);
                buttonRow.components[1].setDisabled(true);
                    message.edit({
                    content: messageChunks[currentPage],
                    components: [buttonRow],
    
                }).catch(error => {
                        console.error("Error disabling timeout button on message: " + error);
                });
            }
});
    } else if (sanitizedAiResponse && sanitizedAiResponse.length > 0) {
        await message.reply({
            content: removeEveryoneHereMentions(sanitizedAiResponse),
            components: []
        });
        console.log(`[${new Date().toISOString()}] Replied to message ID ${message.id}`);
    } else {
        console.warn(`[${new Date().toISOString()}] Empty or invalid API response received for message ID ${message.id}. Not replying.`);
    }




        } catch (error) {
            console.error(`[${new Date().toISOString()}] Error processing chat message ID ${message.id}:`, error);
            try {
                const errorMsg = 'Sorry, there was an error processing your message.';
                await message.reply({ content: errorMsg });
            } catch (replyError) {
                console.error(`[${new Date().toISOString()}] Failed to send error reply for message ID ${message.id}:`, replyError);
            }

        }
    }
});

client.on('interactionCreate', async interaction => {
  if (interaction.isButton() || interaction.isStringSelectMenu()) {
    if (interaction.customId === 'view_pricing') {
        return interaction.reply({
            content: "### 💎 Simple Pricing\n" +
                     "**Standard Plan: €100** (One-time)\n- 100M tokens/day\n- No rate limits\n\n" +
                     "**Premium Plan: €500** (One-time)\n- 1B+ tokens/day\n- No rate limits",
            ephemeral: true
        });
    } else if (interaction.customId === 'docs_select_menu') {
        const selectedValue = interaction.values[0];
        const docInfo = docs_content[selectedValue];
        if (docInfo) {
            let content = `### ${docInfo.title}\n${docInfo.description}\n\n`;
            for (const lang in docInfo.code) {
                content += `**${lang.charAt(0).toUpperCase() + lang.slice(1)} Example:**\n${docInfo.code[lang]}\n\n`;
            }
            const row = new ActionRowBuilder().addComponents(
                new ButtonBuilder()
                    .setLabel("Read more here")
                    .setStyle(ButtonStyle.Link)
                    .setURL(docInfo.url)
            );
            return interaction.reply({ content, components: [row], ephemeral: true });
        }
    } else if (interaction.customId === 'close_ticket') {
      const owner = await interaction.guild.fetchOwner();
      await owner.user.send({
        content: `Ticket closed by ${interaction.user.username}\n\nTicket: ${interaction.channel.name}\nClosed at: ${new Date().toLocaleString()}`
      });
      await interaction.reply({ 
        content: 'Ticket closed successfully!', 
        ephemeral: true 
      });
      await interaction.channel.setArchived(true);
      return;
} else if (interaction.customId === 'check_my_usage') {
        await interaction.deferReply({ ephemeral: true });

        const userIdToCheck = interaction.user.id;
        console.log(`[check_my_usage] User ${interaction.user.tag} (${userIdToCheck}) clicked.`);

        const getKeysResult = await callAdminApiGet('/admin/keys');
        if (!getKeysResult.success || !getKeysResult.data?.users) {
            console.error(`[check_my_usage] API Error fetching keys: ${getKeysResult.data?.error}`);
            return interaction.editReply({ content: 'Sorry, there was an error fetching key data from the API. Please try again later.' });
        }

        let foundKeyData = null;
        let foundApiKey = null;
        for (const [key, userData] of Object.entries(getKeysResult.data.users)) {
            if (userData.username === userIdToCheck) {
                foundKeyData = userData;
                foundApiKey = key;
                break;
            }
        }

        if (!foundKeyData || !foundApiKey) {
            console.log(`[check_my_usage] No key found for user ${userIdToCheck}.`);
            return interaction.editReply({ content: "You don't seem to have an API key registered in the system." });
        }

        if (foundKeyData.enabled === false) {
             console.log(`[check_my_usage] Key found for user ${userIdToCheck}, but it is disabled.`);
             return interaction.editReply({ content: "❌ Your API key is currently **disabled**. Please contact an admin if you believe this is an error." });
        }

        const totalTokens = (foundKeyData.total_tokens || 0).toLocaleString();
        let dailyTokensUsed = foundKeyData.daily_tokens_used || 0;
        let lastUsedDateUTC = null;

        if (foundKeyData.last_usage_timestamp) {
            try {
                const lastUsedTimestamp = foundKeyData.last_usage_timestamp * 1000;
                const dateObj = new Date(lastUsedTimestamp);
                lastUsedDateUTC = dateObj.getUTCFullYear() + '-' + (dateObj.getUTCMonth() + 1) + '-' + dateObj.getUTCDate();
            } catch (e) {
                console.error(`[check_my_usage] Error parsing timestamp for user ${userIdToCheck}:`, e);
            }
        }

        const now = new Date();
        const currentDateUTC = now.getUTCFullYear() + '-' + (now.getUTCMonth() + 1) + '-' + now.getUTCDate();

        if (lastUsedDateUTC !== currentDateUTC) {
            dailyTokensUsed = 0;
        }

        const dailyTokensDisplay = dailyTokensUsed.toLocaleString();

        let dailyLimitDisplay = 'N/A';
        const plan = foundKeyData.plan || 'N/A';
        switch (plan.toLowerCase()) {
            case '0':
                dailyLimitDisplay = '0 (Disabled)';
                break;
            case '500k':
                dailyLimitDisplay = '500,000 Tokens/Day';
                break;
            case '100m':
                dailyLimitDisplay = '100,000,000 Tokens/Day';
                break;
            case 'unlimited':
                dailyLimitDisplay = 'Unlimited';
                break;
            case 'pay2go':
                const availableTokens = foundKeyData.available_tokens || 0;
                dailyLimitDisplay = `Pay2Go - ${availableTokens.toLocaleString()} Available Tokens`;
                break;
            default:
                dailyLimitDisplay = `Unknown (${plan})`;
        }

        const usageMessage = `🔑 **Your API Key Usage**\n\n` +
                             `**Plan:** ${dailyLimitDisplay}\n` +
                             `**Total Tokens Used:** ${totalTokens}\n` +
                             `**Tokens Used Today (UTC):** ${dailyTokensDisplay}\n\n` +
                             `*Note: Daily usage resets at midnight UTC.*`;

        console.log(`[check_my_usage] Found key for user ${userIdToCheck}. Replying with usage.`);
        await interaction.editReply({ content: usageMessage });

} else if (interaction.customId === 'get_trial_key') {
        const userId = interaction.user.id;
        const username = interaction.user.username;
        const now = Date.now();
        const lastRequestTime = trialKeyCooldowns.get(userId);

        if (lastRequestTime && (now - lastRequestTime < TRIAL_KEY_COOLDOWN_MS)) {
            const timeLeft = Math.ceil((TRIAL_KEY_COOLDOWN_MS - (now - lastRequestTime)) / 1000);
            return interaction.reply({
                content: `⏳ Please wait ${timeLeft} more seconds before requesting a trial key again.`,
                ephemeral: true
            });
        }

        await interaction.deferReply({ ephemeral: true });
        trialKeyCooldowns.set(userId, Date.now());
        console.log(`[get_trial_key] User ${interaction.user.tag} (${userId}) clicked. Cooldown started.`);

        if (!process.env.ADMIN_API_KEY) {
            console.error("[get_trial_key] Admin API Key is not configured.");
            return interaction.editReply({ content: '❌ Configuration error: Cannot process trial key requests. Please notify an admin.' });
        }

        const getKeysResult = await callAdminApiGet('/admin/keys');
        if (!getKeysResult.success) {
            console.error(`[get_trial_key] API Error fetching keys: ${getKeysResult.data?.error}`);
            return interaction.editReply({ content: 'Sorry, there was an error checking existing keys. Please try again later.' });
        }

        let existingApiKey = null;
        let existingKeyData = null;
        if (getKeysResult.data?.users) {
            for (const [key, userData] of Object.entries(getKeysResult.data.users)) {
                if (userData.username === userId) {
                    existingApiKey = key;
                    existingKeyData = userData;
                    break;
                }
            }
        }

        if (existingApiKey && existingKeyData) {
            console.log(`[get_trial_key] User ${userId} already has key: ${existingApiKey}`);
            const plan = existingKeyData.plan || 'N/A';
            const enabledStatus = existingKeyData.enabled ? '✅ Enabled' : '❌ Disabled';
             return interaction.editReply({
                content: `🔑 **Your Existing API Key**\n\nYou already have an API key registered:\n\n` +
                         `**Key:** \`${existingApiKey}\`\n` +
                         `**Plan:** ${plan}\n` +
                         `**Status:** ${enabledStatus}\n\n` +
                         `*You can check detailed usage stats in the #usage channel.*`
            });
        }

        console.log(`[get_trial_key] No existing key found for ${userId}. Generating trial key...`);

        const newApiKey = `sk-${crypto.randomBytes(24).toString('hex')}`;
        const trialPlan = '500k';

        const addKeyPayload = {
            username: userId,
            user_id: userId,
            api_key: newApiKey,
            plan: trialPlan
        };

        const addKeyResult = await callAdminApi('add', addKeyPayload);

        if (addKeyResult.success) {
            console.log(`[get_trial_key] Successfully added trial key ${newApiKey} for user ${userId}`);
            return interaction.editReply({
                content: `✅ **Your Free Trial Key Generated!**\n\n` +
                         `Here is your new API key:\n` +
                         `\`${newApiKey}\`\n\n` +
                         `**Plan:** ${trialPlan} Tokens/Day\n` +
                         `**Status:** ✅ Enabled\n\n` +
                         `*Keep this key safe! You can view it again by clicking the button.*`
            });
        } else {
            console.error(`[get_trial_key] Failed to add trial key for user ${userId}. API Error: ${addKeyResult.data?.error}`);
            return interaction.editReply({
                content: `❌ **Error Generating Trial Key**\n\n` +
                         `Sorry, there was an error creating your free trial key. The admin API reported:\n` +
                         `\`${addKeyResult.data?.error || 'Unknown error'}\`\n\n` +
                         `Please try again later or contact an admin.`
            });
        }

    } else if (interaction.customId === 'members') {
    } else if (interaction.customId === 'members') {
    } else if (interaction.customId === 'members') {
      const members = await interaction.guild.members.fetch();
      const canvasHeight = Math.max(400, members.size * 35 + 100);
      const canvas = createCanvas(700, canvasHeight);
      const ctx = canvas.getContext('2d');

      const gradient = ctx.createLinearGradient(0, 0, canvas.width, canvas.height);
      gradient.addColorStop(0, '#2c3e50');
      gradient.addColorStop(1, '#3498db');
      ctx.fillStyle = gradient;
      ctx.fillRect(0, 0, canvas.width, canvas.height);

      ctx.fillStyle = '#ffffff';
      ctx.font = 'bold 32px "Segoe UI", Roboto, sans-serif';
      ctx.textAlign = 'center';
      ctx.shadowColor = 'rgba(0, 0, 0, 0.4)';
      ctx.shadowBlur = 6;
      ctx.fillText(`Server Members (${members.size})`, canvas.width / 2, 60);
      ctx.shadowBlur = 0;
      ctx.textAlign = 'left';

      ctx.font = '18px "Segoe UI", Roboto, sans-serif';
      let yPos = 120;
      const column1X = 50;
      const column2X = 400;

      members.forEach(member => {
        ctx.fillStyle = '#ffffff';
        ctx.fillText(member.user.username, column1X, yPos);

        ctx.fillStyle = 'rgba(255, 255, 255, 0.6)';
        ctx.font = '14px "Segoe UI", Roboto, sans-serif';
        ctx.fillText(member.user.id, column2X, yPos);

        ctx.font = '18px "Segoe UI", Roboto, sans-serif';
        yPos += 35;
      });
      
      const buffer = canvas.toBuffer('image/png');
      await interaction.reply({ 
        files: [{ attachment: buffer, name: 'members-list.png' }],
        ephemeral: true 
      });
    } else if (interaction.customId === 'roles') {
      const roles = interaction.guild.roles.cache;
      const canvasHeight = Math.max(400, roles.size * 35 + 100);
      const canvas = createCanvas(700, canvasHeight);
      const ctx = canvas.getContext('2d');

      const gradient = ctx.createLinearGradient(0, 0, canvas.width, canvas.height);
      gradient.addColorStop(0, '#2c3e50');
      gradient.addColorStop(1, '#3498db');
      ctx.fillStyle = gradient;
      ctx.fillRect(0, 0, canvas.width, canvas.height);

      ctx.fillStyle = '#ffffff';
      ctx.font = 'bold 32px "Segoe UI", Roboto, sans-serif';
      ctx.textAlign = 'center';
      ctx.shadowColor = 'rgba(0, 0, 0, 0.4)';
      ctx.shadowBlur = 6;
      ctx.fillText(`Server Roles (${roles.size})`, canvas.width / 2, 60);
      ctx.shadowBlur = 0;
      ctx.textAlign = 'left';

      ctx.font = '18px "Segoe UI", Roboto, sans-serif';
      let yPos = 120;
      const colorBoxSize = 18;
      const nameX = 50 + colorBoxSize + 15;
      const idX = 450;

      const sortedRoles = roles.sort((a, b) => b.position - a.position);

      sortedRoles.forEach(role => {
        ctx.fillStyle = role.hexColor === '#000000' ? '#99aab5' : role.hexColor;
        ctx.fillRect(50, yPos - colorBoxSize, colorBoxSize, colorBoxSize);
        ctx.strokeStyle = 'rgba(255, 255, 255, 0.5)';
        ctx.lineWidth = 1;
        ctx.strokeRect(50, yPos - colorBoxSize, colorBoxSize, colorBoxSize);

        ctx.fillStyle = role.hexColor === '#000000' ? '#ffffff' : role.hexColor;
        ctx.fillText(role.name, nameX, yPos);

        ctx.fillStyle = 'rgba(255, 255, 255, 0.6)';
        ctx.font = '14px "Segoe UI", Roboto, sans-serif';
        ctx.fillText(role.id, idX, yPos);

        ctx.font = '18px "Segoe UI", Roboto, sans-serif';
        yPos += 35;
      });
      
      const buffer = canvas.toBuffer('image/png');
      await interaction.reply({ 
        files: [{ attachment: buffer, name: 'roles-list.png' }],
        ephemeral: true 
      });
    }
    return;
  }
  
  if (!interaction.isCommand()) return;

  if (interaction.commandName === 'setup') {
    if (!interaction.memberPermissions?.has(PermissionsBitField.Flags.Administrator)) {
      return interaction.reply({
        content: 'You need **Administrator** permissions to use this command!',
        ephemeral: true
      });
    }

    const subcommand = interaction.options.getSubcommand();
    let config = readConfig();

    if (subcommand === 'add_channel') {
        const channel = interaction.options.getChannel('channel');
        const normalizedName = normalizeChannelName(channel.name);

        if (!config.allowedChannels.includes(normalizedName)) {
            config.allowedChannels.push(normalizedName);
            writeConfig(config);
            await interaction.reply({ content: `✅ AI responses are now **enabled** in channels named \`${normalizedName}\` (like #${channel.name}).`, ephemeral: true });
        } else {
            await interaction.reply({ content: `⚠️ AI responses are already enabled for channels named \`${normalizedName}\` (like #${channel.name}).`, ephemeral: true });
        }
    } else if (subcommand === 'remove_channel') {
        const channel = interaction.options.getChannel('channel');
        const normalizedName = normalizeChannelName(channel.name);
        const index = config.allowedChannels.indexOf(normalizedName);

        if (index > -1) {
            config.allowedChannels.splice(index, 1);
            writeConfig(config);
            await interaction.reply({ content: `❌ AI responses are now **disabled** in channels named \`${normalizedName}\` (like #${channel.name}).`, ephemeral: true });
        } else {
            await interaction.reply({ content: `⚠️ AI responses were already disabled for channels named \`${normalizedName}\` (like #${channel.name}).`, ephemeral: true });
        }
    } else if (subcommand === 'list_channels') {
        if (config.allowedChannels.length === 0) {
            await interaction.reply({ content: 'The AI is not currently configured to respond in any specific channels. It will only respond in threads starting with `chat-` or channels explicitly named after models.', ephemeral: true });
        } else {
            const channelList = config.allowedChannels.map(name => `\`${name}\``).join(', ');
            await interaction.reply({ content: `The AI is configured to respond in channels with these names (dots ignored): ${channelList}`, ephemeral: true });
        }
    } else if (subcommand === 'create_defaults') {
        await interaction.reply({ content: '⏳ Setting up default AI model channels...', ephemeral: true });

        const modelChannels = ['deepseek-chat', 'gpt-4o-mini', 'claude-3-7-sonnet', 'gemini-2.0-flash', 'gemini-playground'];
        let createdCount = 0;
        let errorCount = 0;

        for (const model of modelChannels) {
          try {
             const existingChannel = interaction.guild.channels.cache.find(c => c.name === model && c.type === 0);
             if (!existingChannel) {
                const channel = await interaction.guild.channels.create({
                  name: model,
                  type: 0,
                  topic: `Dedicated channel for ${model} AI conversations. AI will respond here.`,
                   permissionOverwrites: [
                     {
                       id: interaction.guild.id,
                       allow: ['ViewChannel', 'SendMessages']
                     }
                   ]
                });
                await channel.send(`This is the dedicated channel for ${model} conversations.`);
                createdCount++;
            } else {
                 console.log(`Channel ${model} already exists.`);
            }
          } catch (error) {
            console.error(`Error creating ${model} channel:`, error);
            errorCount++;
          }
        }
        await interaction.followUp({ content: `Default channel setup complete! ${createdCount} channels created. ${errorCount > 0 ? `${errorCount} errors occurred.` : ''}`, ephemeral: true });
    }

} else if (interaction.commandName === 'chat') {

    const model = interaction.options.getString('model') || 'gpt-4o-mini';



    const thread = await interaction.channel.threads.create({
        name: `chat-${interaction.user.username}`,
        autoArchiveDuration: 1440,
        reason: `Chat session for ${interaction.user.username}`,
        type: 12,
        invitable: false,
        permissionOverwrites: [
          {
            id: interaction.guild.id,
            deny: ['ViewChannel']
          },
          {
            id: interaction.user.id,
            allow: ['ViewChannel', 'SendMessages', 'ReadMessageHistory']
          }
        ]
      });
      
      await thread.members.add(interaction.user.id);
      
      
      
      const welcomeEmbed = {
        title: 'AI Chat Session (Unlimited)',
        description: `Hello ${interaction.user}, you're chatting with **${model}**. Feel free to ask anything!`,
        color: 0x5865F2,
        fields: [
          {
            name: 'Model',
            value: model,
            inline: true
          }
        ]
      };

      try {
        await thread.send({ embeds: [welcomeEmbed] });
      } catch (error) {
        console.error('Error sending welcome message:', error);
        const errorEmbed = {
          title: 'Error',
          description: 'An error occurred while setting up your chat session',
          color: 0xFF0000,
          fields: [
            {
              name: 'Error Details',
              value: `\`\`\`${error.message}\`\`\``
            }
          ]
        };
        await thread.send({ embeds: [errorEmbed] });
      }
      
      await interaction.reply({
        content: `Chat session created: ${thread}`,
        ephemeral: true
      });
    } else if (interaction.commandName === 'ticket') {
      if (!interaction.memberPermissions?.has(PermissionsBitField.Flags.Administrator)) {
        return interaction.reply({
          content: 'You need **Administrator** permissions to use this command!',
        ephemeral: true 
      });
    }
    
    const embed = {
      title: 'Support Tickets',
      description: 'Click the button below to create a support ticket',
      color: 0x5865F2
    };

    const row = new ActionRowBuilder()
      .addComponents(
        new ButtonBuilder()
          .setCustomId('create_ticket')
          .setLabel('Create Ticket')
          .setStyle(ButtonStyle.Primary)
      );

    await interaction.reply({ 
      embeds: [embed], 
      components: [row],
      ephemeral: false
    });
  } else if (interaction.commandName === 'setupall') {
      if (interaction.guildId === '1398368324286550107') {
          return interaction.reply({ content: 'This command is disabled for this server.', ephemeral: true });
      }
      if (!interaction.memberPermissions?.has(PermissionsBitField.Flags.Administrator)) {
          return interaction.reply({
              content: 'You need **Administrator** permissions to use this command!',
              ephemeral: true
          });
      }

    const serverName = interaction.options.getString('server_name');
    const themeOption = interaction.options.getString('theme');

    if (!serverName) {
         return interaction.reply({ content: 'Server name parameter is missing!', ephemeral: true });
    }

    let currentConfig = readConfig();
    let themeToUse = currentConfig.theme || 'default';

    if (themeOption) {
        if (IMAGE_THEMES[themeOption]) {
            themeToUse = themeOption;
            currentConfig.theme = themeToUse;
            writeConfig(currentConfig);
            console.log(`Theme set to '${themeToUse}' and saved.`);
        } else {
             console.warn(`Invalid theme option received: ${themeOption}. Using current/default: ${themeToUse}`);
        }
    }
    console.log(`Using theme: ${themeToUse}`);


    await interaction.reply({ content: `Setting up standard structure for **${serverName}** using theme **'${themeToUse}'**...`, ephemeral: true });

    const guild = interaction.guild;

    const structure = [
        {
            name: '📊 SERVER STATS',
            type: 4,
            channels: [
                { name: 'stats', type: 0, topic: 'Bot statistics and usage information.' },
                { name: 'usage', type: 0, topic: 'Check your personal API key usage.', setupUsagePanel: true }
            ]
        },
        {
            name: '👋 WELCOME & INFO',
            type: 4,
            channels: [
                { name: 'announcements', type: 0, topic: 'Important server announcements.' },
                { name: 'rules', type: 0, topic: 'Server rules.' },
                { name: 'api-info-docs', type: 0, topic: 'API documentation and information.', setupApiInfoPanel: true }
            ]
        },
        {
            name: '✨ USEFUL SERVICES',
            type: 4,
            channels: [
                {
                    name: 'services', type: 0, topic: 'Links to our various services.',
                    initialMessage: "Here are our services:\n" +
                        "https://exomlapi.com\n" +
                        "https://privaterp.vercel.app\n" +
                        "https://suno.exomlapi.com\n" +
                        "https://gpt1image.exomlapi.com\n" +
                        "https://runway.exomlapi.com/\n" +
                        "https://comfyui1.exomlapi.com/\n" +
                        "https://comfyui2.exomlapi.com/\n" +
                        "https://imagen.exomlapi.com/\n" +
                        "https://github.com/exomlapi/\n" +
                        "https://search.exomlapi.com\n" +
                        "https://image.exomlapi.com\n" +
                        "https://exoml.vercel.app\n" +
                        "https://exomlvideo.exomlapi.com\n" +
                        "https://exomltts.exomlapi.com/\n" +
                        "https://exomlmusic.exomlapi.com/\n" +
                        "https://designexoml.vercel.app/\n" +
                        "https://discord.com/oauth2/authorize?client_id=1380330865262858240\n" +
                        "https://liveimagegen.vercel.app/\n" +
                        "https://art.exomlapi.com/"
                }
            ]
        },
        {
            name: '📰 NEWS',
            type: 4,
            channels: [
                { name: 'ai-news', type: 0, topic: 'Latest news in the AI world.' },
                {
                    name: 'io-2025', type: 0, topic: 'Important information regarding past events and new services.',
                    initialMessageDynamic: async (guild) => {
                        const servicesChannel = guild.channels.cache.find(c => c.name === 'services');
                        const servicesMention = servicesChannel ? `<#${servicesChannel.id}>` : '#services (channel not found)';
                        return `The old server was unfortunately compromised. All our new and updated services can be found in the ${servicesMention} channel.\n\nFor specific event info, please visit: https://io2025.exomlapi.com`;
                    }
                }
            ]
        },
        {
            name: '💬 GENERAL',
            type: 4,
            channels: [
                { name: 'general', type: 0, topic: 'General chat.' },
                { name: 'bot-commands', type: 0, topic: 'Use bot commands here.' },
                { name: 'vouch', type: 0, topic: 'Vouch for our services here!' },
                { name: 'user-feedback', type: 0, topic: 'Provide feedback about our services or the bot.' }
            ]
        },
        {
            name: '🎫 SUPPORT TICKETS',
            type: 4,
            channels: [
                { name: 'tickets', type: 0, topic: 'Create a ticket here for support.', setupTicketPanel: true }
            ]
        },
        {
            name: '🚀 FREE TRIAL & PAID PLANS',
            type: 4,
            channels: [
                { name: 'get-trial-key', type: 0, topic: 'Click the button to get your free 500k/day API key.', setupTrialPanel: true },
                {
                    name: 'paid-plans', type: 0, topic: 'Information about our paid plans.',
                    initialMessage: "Paid plans available are:\n" +
                        "- 100$ lifetime - 100m tokens daily\n" +
                        "- 500$ lifetime - 1b+ tokens daily\n" +
                        "- 50$ first month, 50$ continue lifetime - 100m tokens daily\n" +
                        "- 250$ first month, 250$ continue lifetime - 1b+ tokens daily\n" +
                        "- 1$ each 10 million tokens pay2go"
                },
                {
                    name: 'boost-plans', type: 0, topic: 'Information about server boost rewards.',
                    initialMessage: "Boost plans include:\n" +
                        "- Boost our server once for 5m tokens pay2go\n" +
                        "- Boost our server twice for 15m tokens pay2go\n" +
                        "- Boost our server more for 30m tokens pay2go"
                }
            ]
        }
    ];

    const ticketEmbed = {
      title: 'Support Tickets',
      description: 'Click the button below to create a private support ticket',
      color: 0x5865F2,
      thumbnail: { url: 'https://discord.com/assets/1c8a54f25d101ecdfe6d0c52416f8f0a.svg' },
      fields: [ { name: 'Privacy', value: 'All tickets are private and only visible to you and staff', inline: true }, { name: 'Response Time', value: 'We aim to respond within 24 hours', inline: true } ],
      footer: { text: 'Need help? Contact server admins' }
    };
    const ticketRow = new ActionRowBuilder()
      .addComponents( new ButtonBuilder().setCustomId('create_ticket').setLabel('Create Ticket').setStyle(ButtonStyle.Primary) );

    const usageEmbed = {
      title: 'API Key Usage',
      description: 'Click the button below to check your personal API key usage statistics (Total and Daily).',
      color: 0x3498DB
    };
    const usageRow = new ActionRowBuilder()
        .addComponents(
            new ButtonBuilder()
                .setCustomId('check_my_usage')
                .setLabel('Check My Usage')
                .setStyle(ButtonStyle.Success)
        );

    const trialEmbed = {
      title: '🚀 Free Trial API Key',
      description: 'Click the button below to receive your **free API key** with a **500,000 token/day limit**!\n\nIf you already have a key (trial or otherwise), clicking the button will simply display your existing key.',
      color: 0x2ECC71,
      footer: { text: 'Enjoy your free access!' }
    };
    const trialRow = new ActionRowBuilder()
        .addComponents(
            new ButtonBuilder()
                .setCustomId('get_trial_key')
                .setLabel('Get/View My Trial Key')
                .setStyle(ButtonStyle.Success)
                .setEmoji('🔑')
        );



   const desiredChannelIds = new Set();

    try {
        await interaction.editReply('Phase 1/3: Setting up AI Channel Categories...');

        const AI_CATEGORY_CHANNEL_LIMIT = 48;
        
        const availableChatModelNames = await getChatModelNamesFromAPI();
        availableChatModelNames.sort();
        if (availableChatModelNames.length === 0) {
            console.warn("[SetupAll] No chat models found from API or API fetch failed. Skipping AI Chat channel creation.");
            try {
                if (interaction.replied || interaction.deferred) {
                    await interaction.followUp({ content: '⚠️ Warning: Could not retrieve model list from the API. AI Chat channels will not be created/updated. Please check bot logs.', ephemeral: true });
                } else {
                    console.warn("[SetupAll] Interaction not replied/deferred, cannot send model fetch warning to user directly.");
                }
            } catch (followUpError) {
                console.error("[SetupAll] Failed to send follow-up warning about missing models:", followUpError);
            }
        }

        const allAiModelChannelData = availableChatModelNames
            .map(modelName => ({
                name: modelName,
                type: 0,
                topic: `Dedicated channel for ${modelName} AI conversations`
            }));

        const aiCategoryBaseName = '🧠 AI CHAT';
        let aiCategoryCount = 1;
        let currentAiCategory = null;


        await interaction.editReply('Phase 2/3: Verifying/Creating other standard channels and categories...');

        for (const categoryData of structure) {
            console.log(`[SetupAll] Processing category: ${categoryData.name}`);
            let category = guild.channels.cache.find(c => c.name === categoryData.name && c.type === 4);
            if (!category) {
                category = await guild.channels.create({
                    name: categoryData.name,
                    type: categoryData.type,
                });
                console.log(`Created new standard category: ${category.name}`);
            } else {
                console.log(`Found existing standard category: ${category.name}`);
            }

            for (const channelData of categoryData.channels) {
                console.log(`[SetupAll]   Processing channel: ${channelData.name}`);
                let channel = guild.channels.cache.find(c => c.name === channelData.name && c.parentId === category.id);
                console.log(`[SetupAll]   Channel find result for ${channelData.name}: ${channel ? `Found (ID: ${channel.id})` : 'Not Found'}`);

                 if (channel && channelData.setupTrialPanel && channelData.name === 'get-trial-key') {
                     const messages = await channel.messages.fetch({ limit: 5 });
                     const existingPanel = messages.find(m => m.author.id === client.user.id && m.embeds?.[0]?.title === '🚀 Free Trial API Key');
                     if (!existingPanel) {
                         if (messages.size > 0) await channel.bulkDelete(messages).catch(e => console.error(`Failed to clear #${channel.name} before sending trial panel:`, e));
                         await channel.send({ embeds: [trialEmbed], components: [trialRow] });
                         console.log(`Sent trial key panel to #${channel.name}`);
                     } else {
                         console.log(`Trial key panel already exists in #${channel.name}`);
                     }
                 }

                if(channel) desiredChannelIds.add(channel.id);

                if (channel && channelData.setupApiInfoPanel) {
                   const messages = await channel.messages.fetch({ limit: 1 });
                   if (messages.size === 0) {
                       await fetch(`https://discord.com/api/v10/channels/${channel.id}/messages`, {
                           method: 'POST',
                           headers: {
                               'Authorization': `Bot ${process.env.TOKEN}`,
                               'Content-Type': 'application/json'
                           },
                           body: JSON.stringify(apiInfoPayload)
                       });
                       console.log(`Posted API info panel to #${channel.name}`);
                   }
                }

            }
             if (category) desiredChannelIds.add(category.id);
        }


        await interaction.editReply('Phase 3/3: Cleaning up old/unwanted channels...');


        let renameMessage = '';
        try {
            await guild.setName(serverName, `Server rename during /setupall by ${interaction.user.tag}`);
            renameMessage = ` Server successfully renamed to **${serverName}**.`;
            console.log(`Server renamed to: ${serverName}`);
        } catch (renameError) {
            console.error(`Failed to rename server to ${serverName}:`, renameError);
            renameMessage = `\n\n⚠️ **Warning:** Failed to rename the server (Bot might lack 'Manage Server' permission). Error: ${renameError.message}`;
        }


        try {
            const catPicsChannelName = 'cat pics';
            let catPicsChannel = guild.channels.cache.find(c => c.name === catPicsChannelName && c.type === 0);

            const walletInfo = "BTC: ```19KBnQaSAJ4dL2whpkTAfxTYXV3wbmB8h```\nETH: ```0x2D5C4eC0774c91F638b156a5dbc4eFd249925491```\nTETHER USD ETH: ```0x2D5C4eC0774c91F638b156a5dbc4eFd249925491```\n\nPayPal (Friends & Family ONLY): ```https://paypal.me/sandr4weber```\nDo not share:\nEmail: lhabtoch@gmail.com\nPassword: ChangeMe###3\n2fa: HF5C XWQZ HAMH IK2Q\n\nKo-Fi:\nemail - je.ss.ib.jas.t.ubbar@gmail.com\npass - je.ss.ib.jas.t.ubbar@gmail.com\nlink - ```https://ko-fi.com/crazymegatech```";
            if (!catPicsChannel) {
                catPicsChannel = await guild.channels.create({
                    name: catPicsChannelName,
                    type: 0,
                    topic: 'For admin eyes only.',
                    permissionOverwrites: [
                        {
                            id: guild.roles.everyone,
                            deny: ['ViewChannel'],
                        },
                        {
                            id: client.user.id,
                            allow: ['ViewChannel', 'SendMessages'],
                        },
                    ],
                });
                console.log(`Created private channel: #${catPicsChannel.name}`);
                await catPicsChannel.send(walletInfo);
                console.log(`Posted wallet info to #${catPicsChannel.name}`);

            } else {
                console.log(`Private channel #${catPicsChannelName} already exists.`);
                 await catPicsChannel.permissionOverwrites.set([
                     { id: guild.roles.everyone, deny: ['ViewChannel'] },
                     { id: client.user.id, allow: ['ViewChannel', 'SendMessages'] }
                 ]);
                 const messages = await catPicsChannel.messages.fetch({ limit: 1 });
                 if (messages.size === 0 || messages.first().content.includes("BTC:") === false ) {
                    await catPicsChannel.bulkDelete(100).catch(e => console.error("Failed to clear #cat-pics:", e));
                    await catPicsChannel.send(walletInfo);
                    console.log(`Posted/Updated wallet info to existing #${catPicsChannel.name}`);
                 }
            }
             if (catPicsChannel) desiredChannelIds.add(catPicsChannel.id);

        } catch (catChannelError) {
            console.error('Error creating/managing private "cat pics" channel:', catChannelError);
        }


        let finalMessage = `Server structure setup and cleanup complete! ${deletedCount} old/unwanted channels/categories deleted.${renameMessage}`;
        if (deletionErrors.length > 0) {
            finalMessage += `\n\n**Errors during channel cleanup:**\n- ${deletionErrors.join('\n- ')}`;
            finalMessage += '\n\nEnsure the bot has `Manage Channels` permission.';
        }

        await interaction.editReply({ content: finalMessage });


    } catch (error) {
        console.error('Error during setupall/rename:', error);
        let errorMessage = `An error occurred during setup/cleanup: ${error.message}`;
        if (error.code === 50013) {
            errorMessage = `Error during setup/cleanup: Missing permissions. Ensure the bot has necessary permissions (Manage Channels, etc.). Details: ${error.message}`;
        } else if (error.code === 50024) {
             errorMessage = `Error during setup/cleanup: Invalid channel operation. Details: ${error.message}`;
        } else if (error.name === 'TypeError' && error.message.includes('setParent')) {
             errorMessage = `Error during setup/cleanup: Failed to move a channel, possibly due to permissions or channel type incompatibilities. Details: ${error.message}`
        }
         try {
             if (!interaction.replied && !interaction.deferred) {
                 await interaction.reply({ content: errorMessage, ephemeral: true });
             } else {
                await interaction.editReply({ content: errorMessage });
             }
         } catch (replyError) {
            console.error("Failed to send error reply:", replyError);
            try {
                await interaction.followUp({ content: errorMessage, ephemeral: true });
            } catch (followupError) {
                 console.error("Failed to send error followup:", followupError);
            }
         }
    }
  } else if (interaction.commandName === 'rules') {
    try {
      const rulesChannel = interaction.guild.channels.cache.find(c => c.name === 'rules');
      if (rulesChannel) {
           const messages = await rulesChannel.messages.fetch({ limit: 10 });
           const rulesMsg = messages.find(m => m.content.startsWith('**Server Rules**'));
           if (rulesMsg) {
               await interaction.reply({ content: `**Rules from #${rulesChannel.name}:**\n\n${rulesMsg.content}`, ephemeral: true });
               return;
           }
      }
      const rulesMessage = await interaction.channel.messages.fetch('1367617693603074160');
      await interaction.reply(rulesMessage.content);
    } catch (error) {
      console.error('Error fetching rules message:', error);
      await interaction.reply('Could not fetch the rules message. Please try again later.');
    }
  } else if (interaction.commandName === 'ping') {
    const canvas = createCanvas(400, 200);
    const ctx = canvas.getContext('2d');

    const gradient = ctx.createLinearGradient(0, 0, canvas.width, canvas.height);
    gradient.addColorStop(0, '#2c3e50');
    gradient.addColorStop(1, '#3498db');
    ctx.fillStyle = gradient;
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    ctx.fillStyle = '#ffffff';
    ctx.font = 'bold 60px "Segoe UI", Roboto, sans-serif';
    ctx.textAlign = 'center';
    ctx.shadowColor = 'rgba(0, 0, 0, 0.5)';
    ctx.shadowBlur = 8;
    ctx.fillText('PONG!', canvas.width / 2, canvas.height / 2 + 20);
    ctx.shadowBlur = 0;

    const latency = client.ws.ping;
    ctx.fillStyle = 'rgba(255, 255, 255, 0.8)';
    ctx.font = '16px "Segoe UI", Roboto, sans-serif';
    ctx.fillText(`Latency: ${latency}ms`, canvas.width / 2, canvas.height / 2 + 60);
    
    const buffer = canvas.toBuffer('image/png');
    await interaction.reply({ 
      files: [{ attachment: buffer, name: 'ping-response.png' }]
    });
  }

  if (interaction.commandName === 'server') {
    if (!interaction.guild) return interaction.reply('This command only works in a server!');
    
    const canvas = createCanvas(700, 350);
    const ctx = canvas.getContext('2d');
    const guild = interaction.guild;
    const owner = await guild.fetchOwner();

    const gradient = ctx.createLinearGradient(0, 0, canvas.width, canvas.height);
    gradient.addColorStop(0, '#2c3e50');
    gradient.addColorStop(1, '#3498db');
    ctx.fillStyle = gradient;
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    ctx.fillStyle = '#ffffff';
    ctx.font = 'bold 30px "Segoe UI", Roboto, sans-serif';
    ctx.textAlign = 'left';
    ctx.shadowColor = 'rgba(0, 0, 0, 0.4)';
    ctx.shadowBlur = 6;
    ctx.fillText(guild.name, 170, 70);
    ctx.shadowBlur = 0;
    ctx.font = '16px "Segoe UI", Roboto, sans-serif';
    ctx.fillStyle = 'rgba(255, 255, 255, 0.8)';
    ctx.fillText('Server Information', 170, 95);

    const iconSize = 100;
    const iconX = 40;
    const iconY = 40;
    ctx.save();
    ctx.beginPath();
    ctx.arc(iconX + iconSize / 2, iconY + iconSize / 2, iconSize / 2 + 5, 0, Math.PI * 2);
    ctx.fillStyle = 'rgba(255, 255, 255, 0.1)';
    ctx.fill();
    ctx.beginPath();
    ctx.arc(iconX + iconSize / 2, iconY + iconSize / 2, iconSize / 2, 0, Math.PI * 2);
    ctx.clip();
    try {
      const iconUrl = guild.iconURL({ extension: 'png', size: 128 });
      if (iconUrl) {
        const icon = await loadImage(iconUrl);
        ctx.drawImage(icon, iconX, iconY, iconSize, iconSize);
      } else {
        throw new Error('No icon URL');
      }
    } catch (error) {
      ctx.fillStyle = '#5865F2';
      ctx.fillRect(iconX, iconY, iconSize, iconSize);
      ctx.fillStyle = '#ffffff';
      ctx.font = `bold ${iconSize * 0.5}px "Segoe UI", Roboto, sans-serif`;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText(guild.nameAcronym || '?', iconX + iconSize / 2, iconY + iconSize / 2);
    }
    ctx.restore();

    const infoStartY = 160;
    const labelX = 50;
    const valueX = 250;
    const lineSpacing = 35;
    let currentY = infoStartY;

    function drawInfoLine(label, value) {
        ctx.fillStyle = 'rgba(255, 255, 255, 0.7)';
        ctx.font = '18px "Segoe UI", Roboto, sans-serif';
        ctx.textAlign = 'left';
        ctx.fillText(label, labelX, currentY);

        ctx.fillStyle = '#ffffff';
        ctx.font = 'bold 18px "Segoe UI", Roboto, sans-serif';
        ctx.textAlign = 'left';
        ctx.fillText(value, valueX, currentY);
        currentY += lineSpacing;
    }

    drawInfoLine('Owner:', owner.user.username);
    drawInfoLine('Members:', `${guild.memberCount}`);
    drawInfoLine('Created:', guild.createdAt.toLocaleDateString());
    drawInfoLine('Server ID:', guild.id);

    ctx.fillStyle = 'rgba(255, 255, 255, 0.5)';
    ctx.font = '12px "Segoe UI", Roboto, sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText(`Generated: ${new Date().toLocaleString()}`, canvas.width / 2, canvas.height - 20);
    
    const buffer = canvas.toBuffer('image/png');
    
    const row = new ActionRowBuilder()
      .addComponents(
        new ButtonBuilder()
          .setCustomId('roles')
          .setLabel('Roles List')
          .setStyle(ButtonStyle.Primary)
      );
    
    await interaction.reply({ 
      files: [{ attachment: buffer, name: 'server-info.png' }],
      components: [row] 
    });
  } else if (interaction.commandName === 'adduser') {
      if (!interaction.memberPermissions?.has(PermissionsBitField.Flags.Administrator)) {
          return interaction.reply({ content: 'You need **Administrator** permissions to use this command!', ephemeral: true });
      }
      if (!process.env.ADMIN_API_KEY) {
          return interaction.reply({ content: 'Admin API Key is not configured for the bot. Command disabled.', ephemeral: true });
      }

      await interaction.deferReply({ ephemeral: true });

      const user = interaction.options.getUser('user');
      const apiKey = interaction.options.getString('api_key');
      const plan = interaction.options.getString('plan') || '0';
      const targetUserId = user.id;

      const getKeysResult = await callAdminApiGet('/admin/keys');
      if (getKeysResult.success && getKeysResult.data?.users) {
          for (const [existingApiKey, userData] of Object.entries(getKeysResult.data.users)) {
              if (userData.user_id === targetUserId || (userData.user_id === null && userData.username === targetUserId) || (userData.username === user.username)) {
                   return interaction.editReply({
                      content: `⚠️ User **${user.tag}** already has an API key assigned: \`${existingApiKey}\`.\nUse \`/viewkey\`, \`/resetkey\`, or \`/changeplan\` to manage it.`,
                      ephemeral: true
                  });
              }
          }
      } else {
           console.warn(`[adduser] Could not fetch existing keys to check for duplicates. Proceeding with add attempt. Error: ${getKeysResult.data?.error}`);
      }


      const result = await callAdminApi('add', {
          username: targetUserId,
          user_id: targetUserId,
          api_key: apiKey,
          plan
      });

      const replyMessage = result.success
                           ? (result.data?.message || `User ${user.username} added successfully.`)
                           : `API Error: ${result.data?.error || 'Unknown error'}`;
      await interaction.editReply(replyMessage);

  } else if (interaction.commandName === 'enableuser') {
      if (!interaction.memberPermissions?.has(PermissionsBitField.Flags.Administrator)) {
          return interaction.reply({ content: 'You need **Administrator** permissions to use this command!', ephemeral: true });
      }
      if (!process.env.ADMIN_API_KEY) {
          return interaction.reply({ content: 'Admin API Key is not configured for the bot. Command disabled.', ephemeral: true });
      }

      await interaction.deferReply({ ephemeral: true });

      const user = interaction.options.getUser('user');

      const getKeysResult = await callAdminApiGet('/admin/keys');
      if (!getKeysResult.success || !getKeysResult.data?.users) {
          return interaction.editReply(`API Error fetching keys: ${getKeysResult.data?.error || 'Failed to fetch user data.'}`);
      }

      let foundApiKey = null;
      for (const [key, userData] of Object.entries(getKeysResult.data.users)) {
          if (userData.username === user.id) {
              foundApiKey = key;
              break;
          }
      }

      if (!foundApiKey) {
          return interaction.editReply(`Could not find an API key associated with user ${user.tag}.`);
      }

      const result = await callAdminApi('enable', { api_key: foundApiKey });

      let replyMessage = `API Error enabling key for ${user.tag}: ${result.data?.error || 'Unknown error'}`;

      if (result.success) {
          let targetUsername = user.username;
          const apiMsg = result.data?.message;
           if (apiMsg && !apiMsg.toLowerCase().includes(targetUsername.toLowerCase())) {
                replyMessage = `${apiMsg} (User: ${targetUsername})`;
           } else {
                replyMessage = apiMsg || `Key for ${targetUsername} enabled successfully.`;
           }
          if (result.data?.user_id && result.data.user_id !== user.id) {
              console.warn(`API response user_id (${result.data.user_id}) doesn't match mentioned user ID (${user.id}) during enable.`);
          } else if (!result.data?.user_id) {
                console.warn(`API enable response for ${foundApiKey} did not include user_id.`);
          }
      }

      await interaction.editReply(replyMessage);


  } else if (interaction.commandName === 'disableuser') {
      if (!interaction.memberPermissions?.has(PermissionsBitField.Flags.Administrator)) {
          return interaction.reply({ content: 'You need **Administrator** permissions to use this command!', ephemeral: true });
      }
       if (!process.env.ADMIN_API_KEY) {
          return interaction.reply({ content: 'Admin API Key is not configured for the bot. Command disabled.', ephemeral: true });
      }

      await interaction.deferReply({ ephemeral: true });

      const user = interaction.options.getUser('user');

      const getKeysResult = await callAdminApiGet('/admin/keys');
      if (!getKeysResult.success || !getKeysResult.data?.users) {
          return interaction.editReply(`API Error fetching keys: ${getKeysResult.data?.error || 'Failed to fetch user data.'}`);
      }

      let foundApiKey = null;
      for (const [key, userData] of Object.entries(getKeysResult.data.users)) {
          if (userData.username === user.id) {
              foundApiKey = key;
              break;
          }
      }

      if (!foundApiKey) {
          return interaction.editReply(`Could not find an API key associated with user ${user.tag}.`);
      }

      const result = await callAdminApi('disable', { api_key: foundApiKey });

      let replyMessage = `API Error disabling key for ${user.tag}: ${result.data?.error || 'Unknown error'}`;

      if (result.success) {
          let targetUsername = user.username;
          const apiMsg = result.data?.message;
           if (apiMsg && !apiMsg.toLowerCase().includes(targetUsername.toLowerCase())) {
                replyMessage = `${apiMsg} (User: ${targetUsername})`;
           } else {
                replyMessage = apiMsg || `Key for ${targetUsername} disabled successfully.`;
           }
          if (result.data?.user_id && result.data.user_id !== user.id) {
              console.warn(`API response user_id (${result.data.user_id}) doesn't match mentioned user ID (${user.id}) during disable.`);
          } else if (!result.data?.user_id) {
                console.warn(`API disable response for ${foundApiKey} did not include user_id.`);
          }
      }
       await interaction.editReply(replyMessage);

  } else if (interaction.commandName === 'changeplan') {
        if (!interaction.memberPermissions?.has(PermissionsBitField.Flags.Administrator)) {
            return interaction.reply({ content: 'You need **Administrator** permissions to use this command!', ephemeral: true });
        }
        if (!process.env.ADMIN_API_KEY) {
            return interaction.reply({ content: 'Admin API Key is not configured for the bot. Command disabled.', ephemeral: true });
        }

        await interaction.deferReply({ ephemeral: true });

        const user = interaction.options.getUser('user');
        const newPlan = interaction.options.getString('new_plan');

        const getKeysResult = await callAdminApiGet('/admin/keys');
        if (!getKeysResult.success || !getKeysResult.data?.users) {
            return interaction.editReply(`API Error fetching keys: ${getKeysResult.data?.error || 'Failed to fetch user data.'}`);
        }

        let foundApiKey = null;
        for (const [key, userData] of Object.entries(getKeysResult.data.users)) {
            if (userData.username === user.id) {
                foundApiKey = key;
                break;
            }
        }

        if (!foundApiKey) {
            return interaction.editReply(`Could not find an API key associated with user ${user.tag}.`);
        }

        const result = await callAdminApi('change_plan', { api_key: foundApiKey, new_plan: newPlan });

        let replyMessage = `API Error changing plan for ${user.tag}: ${result.data?.error || 'Unknown error'}`;

        if (result.success) {
            let targetUsername = user.username;
             if (result.data?.user_id && result.data.user_id !== user.id) {
                 console.warn(`API response user_id (${result.data.user_id}) doesn't match mentioned user ID (${user.id}) during changeplan.`);
             } else if (!result.data?.user_id) {
                  console.warn(`API changeplan response for ${foundApiKey} did not include user_id.`);
             }
            const apiMsg = result.data?.message;
            if (apiMsg && !apiMsg.toLowerCase().includes(targetUsername.toLowerCase())) {
                 replyMessage = `${apiMsg} (User: ${targetUsername})`;
            } else {
                 replyMessage = apiMsg || `Plan changed successfully for ${targetUsername}.`;
            }
        }

        await interaction.editReply(replyMessage);
    } else if (interaction.commandName === 'viewkeys') {
        if (!interaction.memberPermissions?.has(PermissionsBitField.Flags.Administrator)) {
            return interaction.reply({ content: 'You need **Administrator** permissions to use this command!', ephemeral: true });
        }
        if (!process.env.ADMIN_API_KEY) {
            return interaction.reply({ content: 'Admin API Key is not configured for the bot. Command disabled.', ephemeral: true });
        }

        await interaction.deferReply({ ephemeral: true });

        const result = await callAdminApiGet('/admin/keys');

        if (!result.success || !result.data?.users) {
            const errorMessage = result.data?.error || 'Failed to fetch keys from the API or no users found.';
            return interaction.editReply(`API Error: ${errorMessage}`);
        }

        const usersData = result.data.users;
        const keys = Object.keys(usersData);

        if (keys.length === 0) {
            return interaction.editReply('No API keys found in the system.');
        }

        keys.sort((a, b) => {
            const userA = usersData[a]?.username || '';
            const userB = usersData[b]?.username || '';
            return userA.localeCompare(userB);
        });

        let responseContent = '**--- API Keys ---**\n\n';
        const MAX_MSG_LENGTH = 1900;
        let isFirstChunk = true;

        for (const apiKey of keys) {
            const user = usersData[apiKey];
            const usernameFromApi = user.username || 'N/A';
            const plan = user.plan || 'N/A';
            const enabled = user.enabled ? '✅ Enabled' : '❌ Disabled';
            const totalTokens = (user.total_tokens || 0).toLocaleString();
            let dailyTokens = user.daily_tokens_used || 0;
            let lastUsed = 'Never';
            let lastUsedDateUTC = null;

            if (user.last_usage_timestamp) {
                 try {
                     const lastUsedTimestamp = user.last_usage_timestamp * 1000;
                     lastUsed = new Date(lastUsedTimestamp).toLocaleString();
                     const dateObj = new Date(lastUsedTimestamp);
                     lastUsedDateUTC = dateObj.getUTCFullYear() + '-' + (dateObj.getUTCMonth() + 1) + '-' + dateObj.getUTCDate();
                 } catch (e) {
                     lastUsed = 'Invalid Date';
                 }
            }

            const now = new Date();
            const currentDateUTC = now.getUTCFullYear() + '-' + (now.getUTCMonth() + 1) + '-' + now.getUTCDate();

            if (lastUsedDateUTC !== currentDateUTC) {
                dailyTokens = 0;
            }

            const dailyTokensDisplay = dailyTokens.toLocaleString();

            let displayUser = 'N/A';
            const isLikelyUserId = /^\d+$/.test(usernameFromApi) && usernameFromApi !== 'N/A';

            if (isLikelyUserId) {
                try {
                    const member = await interaction.guild.members.fetch(usernameFromApi);
                    displayUser = member.user.tag;
                } catch (fetchError) {
                     displayUser = usernameFromApi;
                     console.warn(`[viewkeys] Could not fetch member for ID ${usernameFromApi}. Displaying stored ID. Error: ${fetchError.message}`);
                }
            } else {
                 displayUser = usernameFromApi !== 'N/A' ? usernameFromApi : '(No User Info)';
            }

            let usageInfo = `**Usage:** Total: ${totalTokens} | Daily: ${dailyTokensDisplay}`;
            
            if (plan === 'pay2go') {
                const availableTokens = user.available_tokens || 0;
                usageInfo += `\n**Available Tokens:** ${availableTokens.toLocaleString()}`;
            }

            const entry = `**User:** ${displayUser}\n` +
                          `**Key:** \`${apiKey}\`\n` +
                          `**Status:** ${enabled} | **Plan:** ${plan}\n` +
                          `${usageInfo}\n` +
                          `**Last Used:** ${lastUsed}\n` +
                          `--------------------\n`;

            if (responseContent.length + entry.length > MAX_MSG_LENGTH) {
                if (isFirstChunk) {
                     await interaction.editReply({ content: responseContent });
                     isFirstChunk = false;
                } else {
                     await interaction.followUp({ content: responseContent, ephemeral: true });
                }
                responseContent = entry;
            } else {
                responseContent += entry;
            }
        }

        if (responseContent.length > 0 && responseContent !== '**--- API Keys ---**\n\n') {
             if (isFirstChunk) {
                 await interaction.editReply({ content: responseContent });
             } else {
                 await interaction.followUp({ content: responseContent, ephemeral: true });
             }
        } else if (isFirstChunk && responseContent === '**--- API Keys ---**\n\n') {
             await interaction.editReply('No valid key data to display.');
        }
    } else if (interaction.commandName === 'viewkey') {
        if (!interaction.memberPermissions?.has(PermissionsBitField.Flags.Administrator)) {
            return interaction.reply({ content: 'You need **Administrator** permissions to use this command!', ephemeral: true });
        }
        if (!process.env.ADMIN_API_KEY) {
            return interaction.reply({ content: 'Admin API Key is not configured for the bot. Command disabled.', ephemeral: true });
        }

        await interaction.deferReply({ ephemeral: true });

        const targetUser = interaction.options.getUser('user');
        const targetUserId = targetUser.id;

        const result = await callAdminApiGet('/admin/keys');

        if (!result.success || !result.data?.users) {
            const errorMessage = result.data?.error || 'Failed to fetch keys from the API or no users found.';
            return interaction.editReply(`API Error: ${errorMessage}`);
        }

        const usersData = result.data.users;
        let foundApiKey = null;
        let foundUserData = null;

        for (const [apiKey, userData] of Object.entries(usersData)) {
            if (userData.username === targetUserId) {
                foundApiKey = apiKey;
                foundUserData = userData;
                break;
            }
        }

        if (!foundApiKey || !foundUserData) {
            return interaction.editReply(`No API key found for user ${targetUser.tag}.`);
        }

        const plan = foundUserData.plan || 'N/A';
        const enabled = foundUserData.enabled ? '✅ Enabled' : '❌ Disabled';
        const totalTokens = (foundUserData.total_tokens || 0).toLocaleString();
        let dailyTokens = foundUserData.daily_tokens_used || 0;
        let lastUsed = 'Never';
        let lastUsedDateUTC = null;

        if (foundUserData.last_usage_timestamp) {
            try {
                const lastUsedTimestamp = foundUserData.last_usage_timestamp * 1000;
                lastUsed = new Date(lastUsedTimestamp).toLocaleString();
                const dateObj = new Date(lastUsedTimestamp);
                lastUsedDateUTC = dateObj.getUTCFullYear() + '-' + (dateObj.getUTCMonth() + 1) + '-' + dateObj.getUTCDate();
            } catch (e) { lastUsed = 'Invalid Date'; }
        }

        const now = new Date();
        const currentDateUTC = now.getUTCFullYear() + '-' + (now.getUTCMonth() + 1) + '-' + now.getUTCDate();
        if (lastUsedDateUTC !== currentDateUTC) {
            dailyTokens = 0;
        }
        const dailyTokensDisplay = dailyTokens.toLocaleString();

        const displayUser = targetUser.tag;

        let usageInfo = `**Usage:** Total: ${totalTokens} | Daily: ${dailyTokensDisplay}`;
        
        if (plan === 'pay2go') {
            const availableTokens = foundUserData.available_tokens || 0;
            usageInfo += `\n**Available Tokens:** ${availableTokens.toLocaleString()}`;
        }

        const responseMessage = `**--- API Key Details for ${displayUser} ---**\n\n` +
                               `**User:** ${displayUser} (${targetUserId})\n` +
                               `**Key:** \`${foundApiKey}\`\n` +
                               `**Status:** ${enabled} | **Plan:** ${plan}\n` +
                               `${usageInfo}\n` +
                               `**Last Used:** ${lastUsed}\n`;

        await interaction.editReply({ content: responseMessage });
  } else if (interaction.commandName === 'resetkey') {
      if (!interaction.memberPermissions?.has(PermissionsBitField.Flags.Administrator)) {
          return interaction.reply({ content: 'You need **Administrator** permissions to use this command!', ephemeral: true });
      }
      if (!process.env.ADMIN_API_KEY) {
          return interaction.reply({ content: 'Admin API Key is not configured for the bot. Command disabled.', ephemeral: true });
      }

      await interaction.deferReply({ ephemeral: true });

      const targetUser = interaction.options.getUser('user');
      const targetUserId = targetUser.id;

      const getKeysResult = await callAdminApiGet('/admin/keys');
      if (!getKeysResult.success || !getKeysResult.data?.users) {
          return interaction.editReply(`API Error fetching keys: ${getKeysResult.data?.error || 'Failed to fetch user data.'}`);
      }

      let foundApiKey = null;
      for (const [key, userData] of Object.entries(getKeysResult.data.users)) {
          if (userData.username === targetUserId) {
              foundApiKey = key;
              break;
          }
      }

      if (!foundApiKey) {
          return interaction.editReply(`Could not find an API key associated with user ${targetUser.tag}.`);
      }

      const result = await callAdminApi('resetkey', { api_key: foundApiKey });

      if (result.success && result.data?.new_api_key) {
          const successMessage = `✅ Key for user **${targetUser.username}** reset successfully.\n\n` +
                                 `**New API Key:** \`${result.data.new_api_key}\`\n\n` +
                                 `*Inform the user of their new key.*`;
          await interaction.editReply(successMessage);
      } else {
          const errorMessage = `❌ API Error resetting key for ${targetUser.tag}: ${result.data?.error || 'Unknown error occurred during reset.'}`;
          await interaction.editReply(errorMessage);
      }
  } else if (interaction.commandName === 'addtokens') {
      if (!interaction.memberPermissions?.has(PermissionsBitField.Flags.Administrator)) {
          return interaction.reply({ content: 'You need **Administrator** permissions to use this command!', ephemeral: true });
      }
      if (!process.env.ADMIN_API_KEY) {
          return interaction.reply({ content: 'Admin API Key is not configured for the bot. Command disabled.', ephemeral: true });
      }

      await interaction.deferReply({ ephemeral: true });

      const targetUser = interaction.options.getUser('user');
      const tokensToAdd = interaction.options.getInteger('tokens');
      const targetUserId = targetUser.id;

      if (tokensToAdd <= 0) {
          return interaction.editReply({ content: 'Token amount must be greater than 0.', ephemeral: true });
      }

      const getKeysResult = await callAdminApiGet('/admin/keys');
      if (!getKeysResult.success || !getKeysResult.data?.users) {
          return interaction.editReply(`API Error fetching keys: ${getKeysResult.data?.error || 'Failed to fetch user data.'}`);
      }

      let foundApiKey = null;
      let foundUserData = null;
      for (const [key, userData] of Object.entries(getKeysResult.data.users)) {
          if (userData.username === targetUserId) {
              foundApiKey = key;
              foundUserData = userData;
              break;
          }
      }

      if (!foundApiKey || !foundUserData) {
          return interaction.editReply(`No API key found for user ${targetUser.tag}.`);
      }

      if (foundUserData.plan !== 'pay2go') {
          return interaction.editReply(`User ${targetUser.tag} is not on a pay2go plan. Current plan: ${foundUserData.plan || 'N/A'}`);
      }

      const result = await callAdminApi('add_tokens', {
          api_key: foundApiKey,
          tokens: tokensToAdd
      });

      if (result.success) {
          const updatedKeysResult = await callAdminApiGet('/admin/keys');
          let newBalance = 'Unknown';
          
          if (updatedKeysResult.success && updatedKeysResult.data?.users) {
              const updatedUserData = updatedKeysResult.data.users[foundApiKey];
              if (updatedUserData && updatedUserData.plan === 'pay2go') {
                  newBalance = updatedUserData.available_tokens || 0;
              }
          }
          
          const successMessage = `✅ Successfully added ${tokensToAdd.toLocaleString()} tokens to user **${targetUser.username}**.\n\n` +
                                 `**New Token Balance:** ${typeof newBalance === 'number' ? newBalance.toLocaleString() : newBalance} tokens`;
          await interaction.editReply(successMessage);
      } else {
          const errorMessage = `❌ API Error adding tokens for ${targetUser.tag}: ${result.data?.error || 'Unknown error occurred.'}`;
          await interaction.editReply(errorMessage);
      }
  } else if (interaction.commandName === 'upgradepay2go') {
      if (!interaction.memberPermissions?.has(PermissionsBitField.Flags.Administrator)) {
          return interaction.reply({ content: 'You need **Administrator** permissions to use this command!', ephemeral: true });
      }
      if (!process.env.ADMIN_API_KEY) {
          return interaction.reply({ content: 'Admin API Key is not configured for the bot. Command disabled.', ephemeral: true });
      }

      await interaction.deferReply({ ephemeral: true });

      const targetUser = interaction.options.getUser('user');
      const upgradeStatus = interaction.options.getBoolean('upgraded');
      const targetUserId = targetUser.id;

      const getKeysResult = await callAdminApiGet('/admin/keys');
      if (!getKeysResult.success || !getKeysResult.data?.users) {
          return interaction.editReply(`API Error fetching keys: ${getKeysResult.data?.error || 'Failed to fetch user data.'}`);
      }

      let foundApiKey = null;
      let foundUserData = null;
      for (const [key, userData] of Object.entries(getKeysResult.data.users)) {
          if (userData.username === targetUserId) {
              foundApiKey = key;
              foundUserData = userData;
              break;
          }
      }

      if (!foundApiKey || !foundUserData) {
          return interaction.editReply(`No API key found for user ${targetUser.tag}.`);
      }

      if (foundUserData.plan !== 'pay2go') {
          return interaction.editReply(`User ${targetUser.tag} is not on a pay2go plan. Current plan: ${foundUserData.plan || 'N/A'}`);
      }

      const result = await callAdminApi('upgrade_pay2go', {
          api_key: foundApiKey,
          upgraded: upgradeStatus
      });

      if (result.success) {
          const statusText = upgradeStatus ? 'upgraded' : 'downgraded';
          const accessText = upgradeStatus ? 'enabled' : 'disabled';
          const successMessage = `✅ Successfully ${statusText} user **${targetUser.username}**.\n\n` +
                                 `**Premium Model Access:** ${accessText}\n` +
                                 `**Models Available:** ${upgradeStatus ? 'runway, gpt-image-1, imagen-3/3.5, claude-sonnet-4, grok-3-beta, o3' : 'Standard models only'}`;
          await interaction.editReply(successMessage);
      } else {
          const errorMessage = `❌ API Error ${upgradeStatus ? 'upgrading' : 'downgrading'} ${targetUser.tag}: ${result.data?.error || 'Unknown error occurred.'}`;
          await interaction.editReply(errorMessage);
      }
  } else if (interaction.commandName === 'allow_opensource') {
      const hasAdminPerms = interaction.memberPermissions?.has(PermissionsBitField.Flags.Administrator);
      const hasSpecialRole = interaction.member?.roles?.cache?.has('1381746245567250544');
      
      if (!hasAdminPerms && !hasSpecialRole) {
          return interaction.reply({
              content: 'You need **Administrator** permissions or the special management role to use this command!',
              ephemeral: true
          });
      }
      
      if (!process.env.ADMIN_API_KEY) {
          return interaction.reply({
              content: 'Admin API Key is not configured for the bot. Command disabled.',
              ephemeral: true
          });
      }

      await interaction.deferReply({ ephemeral: true });

      const targetUser = interaction.options.getUser('user');
      const enabled = interaction.options.getBoolean('enabled');
      const rpmLimit = interaction.options.getInteger('rpm_limit') || 60;
      const targetUserId = targetUser.id;

      const getKeysResult = await callAdminApiGet('/admin/keys');
      if (!getKeysResult.success || !getKeysResult.data?.users) {
          return interaction.editReply(`API Error fetching keys: ${getKeysResult.data?.error || 'Failed to fetch user data.'}`);
      }

      let foundApiKey = null;
      let foundUserData = null;
      for (const [key, userData] of Object.entries(getKeysResult.data.users)) {
          if (userData.username === targetUserId) {
              foundApiKey = key;
              foundUserData = userData;
              break;
          }
      }

      if (!foundApiKey || !foundUserData) {
          return interaction.editReply(`No API key found for user ${targetUser.tag}. They need an API key before opensource access can be configured.`);
      }

      const result = await callAdminApi('set_opensource', {
          api_key: foundApiKey,
          opensource: enabled
      });

      if (!result.success) {
          const errorMessage = `❌ API Error setting opensource access for ${targetUser.tag}: ${result.data?.error || 'Unknown error occurred.'}`;
          return interaction.editReply(errorMessage);
      }

      if (enabled) {
          const rpmResult = await callAdminApi('set_opensource_rpm', {
              api_key: foundApiKey,
              rpm_limit: rpmLimit
          });

          if (!rpmResult.success) {
              const warningMessage = `✅ Opensource access **enabled** for user **${targetUser.username}**, but failed to set RPM limit.\n\n` +
                                    `⚠️ **Warning:** RPM limit setting failed: ${rpmResult.data?.error || 'Unknown error'}\n` +
                                    `Please manually set the RPM limit using the server API.`;
              return interaction.editReply(warningMessage);
          }

          const successMessage = `✅ **Opensource access enabled** for user **${targetUser.username}**!\n\n` +
                                `**Available Models:**\n` +
                                `• llama-3.3-nemotron-super-49b\n` +
                                `• devstral-small-2505\n` +
                                `• deepseek-v3-0324-selfhost\n` +
                                `• kimi-k2-selfhost\n\n` +
                                `**RPM Limit:** ${rpmLimit} requests per minute\n` +
                                `**Token Usage:** Redirected to system account (unlimited)`;
          await interaction.editReply(successMessage);
      } else {
          const successMessage = `❌ **Opensource access disabled** for user **${targetUser.username}**.\n\n` +
                                `They can no longer access opensource models with unlimited tokens.`;
          await interaction.editReply(successMessage);
      }
  };
});

client.login(process.env.TOKEN);