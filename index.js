const { Client, GatewayIntentBits, ActivityType, Events } = require('discord.js');
require('dotenv').config();
const express = require('express');
const path = require('path');

// Create Discord client with necessary intents
const client = new Client({
  intents: [
    GatewayIntentBits.Guilds
  ],
});

// Set up Express server
const app = express();
const port = process.env.PORT || 3000;

app.get('/', (req, res) => {
  const htmlPath = path.join(__dirname, 'index.html');
  res.sendFile(htmlPath);
});

// Status configuration
const statusConfig = {
  messages: ["🎧 Listening to ArctixMC", "🎮 Playing ArctixMC"],
  types: ['dnd', 'idle'],
  interval: 10000, // 10 seconds
  heartbeatInterval: 30000 // 30 seconds
};

let currentStatusIndex = 0;
let currentTypeIndex = 0;
let statusInterval = null;
let reconnectAttempts = 0;
const maxReconnectAttempts = 5;

// Function to update bot status with proper error handling
async function updateStatus() {
  try {
    if (!client || !client.user) {
      console.log('\x1b[33m[ STATUS ]\x1b[0m', 'Client not ready, skipping status update');
      return;
    }

    const currentMessage = statusConfig.messages[currentStatusIndex];
    const currentType = statusConfig.types[currentTypeIndex];
    
    // Set presence with proper activity type
    await client.user.setPresence({
      activities: [{ 
        name: currentMessage, 
        type: ActivityType.Custom 
      }],
      status: currentType,
    });
    
    console.log('\x1b[33m[ STATUS ]\x1b[0m', `Updated status to: ${currentMessage} (${currentType})`);
    
    // Update indices for next status rotation
    currentStatusIndex = (currentStatusIndex + 1) % statusConfig.messages.length;
    currentTypeIndex = (currentTypeIndex + 1) % statusConfig.types.length;
  } catch (error) {
    console.error('\x1b[31m[ ERROR ]\x1b[0m', 'Failed to update status:', error);
    
    // Reset status on error to prevent ghost status
    try {
      await client.user.setPresence({
        activities: [{ name: 'Status Reset', type: ActivityType.Custom }],
        status: 'online',
      });
    } catch (resetError) {
      console.error('\x1b[31m[ ERROR ]\x1b[0m', 'Failed to reset status:', resetError);
    }
  }
}

// Function to start status rotation
function startStatusRotation() {
  // Clear any existing interval
  if (statusInterval) {
    clearInterval(statusInterval);
  }
  
  // Update status immediately
  updateStatus();
  
  // Set up interval for status rotation
  statusInterval = setInterval(updateStatus, statusConfig.interval);
  console.log('\x1b[36m[ INFO ]\x1b[0m', `Status rotation started (${statusConfig.interval}ms interval)`);
}

// Heartbeat function to keep the bot alive
function startHeartbeat() {
  setInterval(() => {
    console.log('\x1b[35m[ HEARTBEAT ]\x1b[0m', `Bot is alive at ${new Date().toLocaleTimeString()}`);
    
    // Check if client is still connected
    if (!client.isReady()) {
      console.log('\x1b[31m[ WARNING ]\x1b[0m', 'Client disconnected, attempting to reconnect...');
      reconnect();
    }
  }, statusConfig.heartbeatInterval);
}

// Function to handle reconnection
async function reconnect() {
  if (reconnectAttempts >= maxReconnectAttempts) {
    console.error('\x1b[31m[ ERROR ]\x1b[0m', 'Max reconnect attempts reached. Exiting...');
    process.exit(1);
  }
  
  reconnectAttempts++;
  console.log('\x1b[33m[ RECONNECT ]\x1b[0m', `Attempt ${reconnectAttempts}/${maxReconnectAttempts}`);
  
  try {
    await login();
  } catch (error) {
    console.error('\x1b[31m[ ERROR ]\x1b[0m', 'Reconnect failed:', error);
    
    // Wait before trying again
    setTimeout(reconnect, 5000);
  }
}

// Login function with error handling
async function login() {
  try {
    await client.login(process.env.TOKEN);
    console.log('\x1b[36m[ LOGIN ]\x1b[0m', `\x1b[32mLogged in as: ${client.user.tag} ✅\x1b[0m`);
    console.log('\x1b[36m[ INFO ]\x1b[0m', `\x1b[35mBot ID: ${client.user.id} \x1b[0m`);
    console.log('\x1b[36m[ INFO ]\x1b[0m', `\x1b[34mConnected to ${client.guilds.cache.size} server(s) \x1b[0m`);
    
    // Reset reconnect attempts on successful login
    reconnectAttempts = 0;
  } catch (error) {
    console.error('\x1b[31m[ ERROR ]\x1b[0m', 'Failed to log in:', error);
    throw error; // Rethrow to be caught by reconnect
  }
}

// Event handlers
client.once(Events.ClientReady, () => {
  console.log('\x1b[36m[ INFO ]\x1b[0m', `\x1b[34mPing: ${client.ws.ping} ms \x1b[0m`);
  startStatusRotation();
  startHeartbeat();
  
  // Start the Express server after bot is ready
  app.listen(port, () => {
    console.log('\x1b[36m[ SERVER ]\x1b[0m', `\x1b[32m SH : http://localhost:${port} ✅\x1b[0m`);
  });
});

// Handle disconnections to prevent ghost status
client.on(Events.ShardDisconnect, () => {
  console.log('\x1b[31m[ DISCONNECT ]\x1b[0m', 'Bot disconnected from Discord');
  
  // Clear status rotation on disconnect
  if (statusInterval) {
    clearInterval(statusInterval);
    statusInterval = null;
  }
});

// Handle reconnections
client.on(Events.ShardReconnecting, () => {
  console.log('\x1b[33m[ RECONNECT ]\x1b[0m', 'Bot is reconnecting to Discord');
});

// Handle successful reconnections
client.on(Events.ShardResume, () => {
  console.log('\x1b[32m[ RESUME ]\x1b[0m', 'Bot reconnected to Discord');
  
  // Restart status rotation after reconnect
  startStatusRotation();
});

// Start the bot
login().catch(error => {
  console.error('\x1b[31m[ FATAL ]\x1b[0m', 'Failed to start bot:', error);
  process.exit(1);
});

// Handle process termination
process.on('SIGINT', () => {
  console.log('\x1b[36m[ SHUTDOWN ]\x1b[0m', 'Bot is shutting down...');
  
  if (statusInterval) {
    clearInterval(statusInterval);
  }
  
  client.destroy();
  process.exit(0);
});

// Export the app for serverless environments
module.exports = app;
