"use client";

import { useState, useRef } from "react";
import { Upload, FileText, ArrowRight, Send } from "lucide-react";

interface EmptyChatStateProps {
  userName: string;
  onUpload: (base64: string, filename: string) => void;
  onCreateScratch: (data: any) => void;
  onSendMessage: (msg: string) => void;
}

export function EmptyChatState({ userName, onUpload, onCreateScratch, onSendMessage }: EmptyChatStateProps) {
  const [mode, setMode] = useState<"options" | "scratch">("options");
  const [inputText, setInputText] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [formData, setFormData] = useState({
    name: "",
    email: "",
    phone: "",
    location: ""
  });

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      const reader = new FileReader();
      reader.onload = (event) => {
        const base64 = event.target?.result as string;
        onUpload(base64, file.name);
      };
      reader.readAsDataURL(file);
    }
  };

  const handleScratchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onCreateScratch(formData);
  };

  return (
    <div className="flex flex-col items-center justify-center text-center w-full max-w-2xl mx-auto mt-12 px-4">
      <div className="mb-6 h-16 w-16 rounded-2xl bg-white flex items-center justify-center shadow-[0_0_40px_rgba(255,255,255,0.15)]">
        <svg
          width="32"
          height="32"
          viewBox="0 0 24 24"
          fill="none"
          stroke="black"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
          <polyline points="14 2 14 8 20 8" />
          <line x1="16" y1="13" x2="8" y2="13" />
          <line x1="16" y1="17" x2="8" y2="17" />
        </svg>
      </div>
      <h2 className="text-2xl font-bold text-white mb-2">
        Hello, {userName}
      </h2>
      <p className="text-neutral-400 mb-10 max-w-md">
        How would you like to start building your AI-architected resume today?
      </p>

      {mode === "options" && (
        <div className="w-full flex flex-col gap-8">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 w-full">
            {/* Upload Option */}
            <button
              onClick={() => fileInputRef.current?.click()}
              className="flex flex-col items-center p-6 rounded-2xl bg-neutral-900 border border-neutral-800 hover:bg-neutral-800 transition-colors group text-left relative overflow-hidden"
            >
              <div className="bg-neutral-800 p-3 rounded-xl mb-4 group-hover:scale-110 transition-transform">
                <Upload className="text-white" size={24} />
              </div>
              <h3 className="text-lg font-semibold text-white mb-1">Upload Resume</h3>
              <p className="text-sm text-neutral-500 text-center">Import an existing PDF to analyze and improve.</p>
              <input
                type="file"
                ref={fileInputRef}
                onChange={handleFileChange}
                accept=".pdf"
                className="hidden"
              />
            </button>

            {/* Create from Scratch Option */}
            <button
              onClick={() => setMode("scratch")}
              className="flex flex-col items-center p-6 rounded-2xl bg-neutral-900 border border-neutral-800 hover:bg-neutral-800 transition-colors group text-left relative overflow-hidden"
            >
              <div className="bg-neutral-800 p-3 rounded-xl mb-4 group-hover:scale-110 transition-transform">
                <FileText className="text-white" size={24} />
              </div>
              <h3 className="text-lg font-semibold text-white mb-1">Create from Scratch</h3>
              <p className="text-sm text-neutral-500 text-center">Start fresh with AI guided sections.</p>
            </button>
          </div>

          <div className="relative">
            <div className="absolute inset-0 flex items-center">
              <div className="w-full border-t border-neutral-800"></div>
            </div>
            <div className="relative flex justify-center text-xs uppercase">
              <span className="bg-black px-4 text-neutral-500">Or just start typing</span>
            </div>
          </div>
          
          <form 
            onSubmit={(e) => {
              e.preventDefault();
              if (inputText.trim()) {
                onSendMessage(inputText);
              }
            }}
            className="relative flex items-center w-full"
          >
            <input 
              type="text"
              value={inputText}
              onChange={e => setInputText(e.target.value)}
              placeholder="Message AI Resume Architect..."
              className="w-full bg-neutral-900 border border-neutral-800 rounded-xl pl-4 pr-12 py-4 text-white focus:outline-none focus:border-neutral-700 shadow-xl"
            />
            <button 
              type="submit"
              disabled={!inputText.trim()}
              className="absolute right-2 p-2 bg-white text-black rounded-lg disabled:opacity-50 disabled:bg-neutral-800 disabled:text-neutral-500 transition-colors"
            >
              <Send size={18} />
            </button>
          </form>
        </div>
      )}

      {mode === "scratch" && (
        <form onSubmit={handleScratchSubmit} className="w-full bg-neutral-900 border border-neutral-800 rounded-2xl p-6 text-left animate-in fade-in zoom-in-95 duration-200">
          <h3 className="text-lg font-semibold text-white mb-4">Basic Information</h3>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-6">
            <div>
              <label className="block text-xs font-medium text-neutral-400 mb-1">Full Name</label>
              <input 
                required
                type="text" 
                value={formData.name}
                onChange={e => setFormData({...formData, name: e.target.value})}
                className="w-full bg-neutral-950 border border-neutral-800 rounded-lg px-3 py-2 text-white focus:outline-none focus:border-neutral-600"
                placeholder="John Doe"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-neutral-400 mb-1">Email</label>
              <input 
                required
                type="email" 
                value={formData.email}
                onChange={e => setFormData({...formData, email: e.target.value})}
                className="w-full bg-neutral-950 border border-neutral-800 rounded-lg px-3 py-2 text-white focus:outline-none focus:border-neutral-600"
                placeholder="john@example.com"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-neutral-400 mb-1">Phone</label>
              <input 
                type="text" 
                value={formData.phone}
                onChange={e => setFormData({...formData, phone: e.target.value})}
                className="w-full bg-neutral-950 border border-neutral-800 rounded-lg px-3 py-2 text-white focus:outline-none focus:border-neutral-600"
                placeholder="+1 (555) 000-0000"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-neutral-400 mb-1">Location</label>
              <input 
                type="text" 
                value={formData.location}
                onChange={e => setFormData({...formData, location: e.target.value})}
                className="w-full bg-neutral-950 border border-neutral-800 rounded-lg px-3 py-2 text-white focus:outline-none focus:border-neutral-600"
                placeholder="City, State"
              />
            </div>
          </div>
          <div className="flex items-center justify-between">
            <button 
              type="button" 
              onClick={() => setMode("options")}
              className="text-sm text-neutral-400 hover:text-white transition-colors"
            >
              Back
            </button>
            <button 
              type="submit"
              className="flex items-center gap-2 bg-white text-black px-4 py-2 rounded-lg text-sm font-semibold hover:bg-neutral-200 transition-colors"
            >
              Start Generating <ArrowRight size={16} />
            </button>
          </div>
        </form>
      )}
    </div>
  );
}
