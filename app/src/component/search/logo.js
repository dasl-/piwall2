import React from 'react';

class Logo extends React.Component {
  render() {
    return (
      <div className='pt-2 pl-2 m-0 position-absolute logo-container'>
        <div className='logo-wrapper'>
          <span className='logo'>piwall</span>
        </div>
      </div>
    );
  }
}

export default Logo;
