module.exports = {
  content: [
    './templates/**/*.html',
    './static/js/**/*.js'
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Source Sans 3', 'Segoe UI', 'sans-serif']
      },
      colors: {
        tsm: {
          blue: '#0056b3',
          dark: '#0f172a',
          steel: '#64748b'
        }
      }
    }
  },
  plugins: []
};
